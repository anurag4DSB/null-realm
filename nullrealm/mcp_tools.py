"""MCP tool implementations wrapping pgvector and Neo4j stores.

These functions are the shared implementation used by both the MCP server
(exposed over Streamable HTTP / SSE) and the LangGraph builtin tools.

Every tool call is traced via OpenTelemetry using OpenInference semantic
conventions so Arize Phoenix displays input, output, user, and metadata
correctly in its trace UI.
"""

import asyncio
import json
import logging
import time
from contextlib import contextmanager

from opentelemetry import trace
from prometheus_client import Counter, Histogram

from nullrealm.context.neo4j_store import Neo4jStore
from nullrealm.context.pgvector_store import PgVectorStore

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("mcp-tools")

# Prometheus metrics
MCP_TOOL_CALLS = Counter(
    "mcp_tool_calls_total",
    "Total MCP tool calls",
    ["tool", "user", "status"],
)
MCP_TOOL_DURATION = Histogram(
    "mcp_tool_duration_seconds",
    "MCP tool call duration in seconds",
    ["tool"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)


async def _write_audit_log(
    user_email: str,
    tool_name: str,
    input_params: dict,
    output_size: int,
    duration_ms: int,
    status: str,
    error_message: str | None = None,
) -> None:
    """Write a row to mcp_audit_log. Fire-and-forget — errors are logged, not raised."""
    try:
        import os
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from nullrealm.registry.models import McpAuditLog

        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:5432/nullrealm",
        )
        engine = create_async_engine(db_url, echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            async with session.begin():
                session.add(McpAuditLog(
                    user_email=user_email,
                    tool_name=tool_name,
                    input_params=input_params,
                    output_size=output_size,
                    duration_ms=duration_ms,
                    status=status,
                    error_message=error_message,
                ))
        await engine.dispose()
    except Exception:
        logger.warning("Failed to write audit log", exc_info=True)


def _get_user_email() -> str:
    """Read the current user's email from shared state module."""
    from nullrealm.mcp_state import get_email
    email = get_email()
    logger.info("_get_user_email: got '%s' from mcp_state", email)
    return email


@contextmanager
def _traced_tool(tool_name: str, input_params: dict):
    """Context manager that creates an OTEL span with OpenInference attributes.

    Phoenix expects these exact attribute names:
      input.value / input.mime_type  → "input" column
      output.value / output.mime_type → "output" column
      user.id                        → user identification
      metadata                       → JSON metadata blob
      session.id                     → session grouping
    """
    with _tracer.start_as_current_span(f"mcp.tool.{tool_name}") as span:
        email = _get_user_email()
        t0 = time.monotonic()

        # OpenInference attributes for Phoenix UI
        span.set_attribute("openinference.span.kind", "TOOL")
        span.set_attribute("input.value", json.dumps(input_params))
        span.set_attribute("input.mime_type", "application/json")
        span.set_attribute("user.id", email)
        span.set_attribute("metadata", json.dumps({
            "tool_name": tool_name,
            "user_email": email,
        }))

        # Container for the tool to set its output
        result = {"output": "", "error": None}
        try:
            yield result
            MCP_TOOL_CALLS.labels(tool=tool_name, user=email, status="success").inc()
        except Exception as exc:
            result["error"] = str(exc)
            span.set_attribute("output.value", f"ERROR: {exc}")
            span.set_attribute("output.mime_type", "text/plain")
            MCP_TOOL_CALLS.labels(tool=tool_name, user=email, status="error").inc()
            raise
        finally:
            duration = time.monotonic() - t0
            duration_ms = round(duration * 1000)
            MCP_TOOL_DURATION.labels(tool=tool_name).observe(duration)
            if result["output"]:
                output_preview = result["output"][:500]
                if len(result["output"]) > 500:
                    output_preview += f"\n... ({len(result['output'])} chars total)"
                span.set_attribute("output.value", output_preview)
                span.set_attribute("output.mime_type", "text/plain")

            # Write audit log (fire-and-forget background task)
            status = "error" if result["error"] else "success"
            try:
                asyncio.get_event_loop().create_task(_write_audit_log(
                    user_email=email,
                    tool_name=tool_name,
                    input_params=input_params,
                    output_size=len(result["output"]),
                    duration_ms=duration_ms,
                    status=status,
                    error_message=result["error"],
                ))
            except Exception:
                logger.warning("Could not schedule audit log write", exc_info=True)


async def do_code_search(query: str, repo: str = "null-realm", k: int = 10) -> str:
    """Embed *query* and return the top-k semantically similar code chunks."""
    with _traced_tool("code_search", {"query": query, "repo": repo, "k": k}) as result:
        store = PgVectorStore()
        try:
            await store.init()
            results = await store.search(query, k=k, repo=repo)
            if not results:
                result["output"] = "No results found."
                return result["output"]
            formatted = []
            for r in results:
                formatted.append(
                    f"[{r['score']:.3f}] {repo}/{r['file_path']}:{r['symbol_name']}"
                    f" ({r['symbol_type']})\n```\n{r['chunk_text'][:2000]}\n```"
                )
            result["output"] = "\n\n".join(formatted)
            return result["output"]
        finally:
            await store.close()


async def do_graph_query(symbol: str, depth: int = 2) -> str:
    """Find all symbols connected to *symbol* within *depth* hops in Neo4j."""
    with _traced_tool("graph_query", {"symbol": symbol, "depth": depth}) as result:
        store = Neo4jStore()
        try:
            results = await store.query_neighbors(symbol, depth)
            if not results:
                result["output"] = f"No neighbors found for symbol '{symbol}'."
                return result["output"]
            lines = [f"Neighbors of '{symbol}' (depth={depth}):"]
            for r in results:
                lines.append(
                    f"  [{r['distance']}] {r['file']}:{r['name']} ({r.get('type', 'unknown')})"
                )
            result["output"] = "\n".join(lines)
            return result["output"]
        finally:
            await store.close()


async def do_graph_path(source: str, target: str) -> str:
    """Find the shortest path between two symbols in the code graph."""
    with _traced_tool("graph_path", {"source": source, "target": target}) as result:
        store = Neo4jStore()
        try:
            results = await store.query_path(source, target)
            if not results:
                result["output"] = f"No path found between '{source}' and '{target}'."
                return result["output"]
            lines = [f"Shortest path from '{source}' to '{target}':"]
            for r in results:
                nodes = r.get("path_nodes", [])
                edges = r.get("edge_types", [])
                path_parts = []
                for i, node in enumerate(nodes):
                    path_parts.append(f"{node['file']}:{node['name']}")
                    if i < len(edges):
                        path_parts.append(f"  --[{edges[i]}]-->")
                lines.extend(path_parts)
            result["output"] = "\n".join(lines)
            return result["output"]
        finally:
            await store.close()


async def do_get_full_chunk(file_path: str, symbol_name: str, repo: str = "null-realm") -> str:
    """Retrieve the full untruncated source code of a single symbol."""
    with _traced_tool("get_full_chunk", {"file_path": file_path, "symbol_name": symbol_name, "repo": repo}) as result:
        store = PgVectorStore()
        try:
            await store.init()
            chunk = await store.get_chunk(file_path, symbol_name, repo)
            if not chunk:
                result["output"] = f"No chunk found for {repo}/{file_path}:{symbol_name}"
                return result["output"]
            lines = chunk["line_end"] - chunk["line_start"]
            header = (
                f"{repo}/{chunk['file_path']}:{chunk['symbol_name']}"
                f" ({chunk['symbol_type']}, lines {chunk['line_start']}-{chunk['line_end']}, {lines} lines)"
            )
            result["output"] = f"{header}\n```\n{chunk['chunk_text']}\n```"
            return result["output"]
        finally:
            await store.close()


async def do_service_map() -> str:
    """Return all file-to-file connections in the codebase graph."""
    with _traced_tool("service_map", {}) as result:
        store = Neo4jStore()
        try:
            results = await store.query_service_map()
            if not results:
                result["output"] = "No cross-file connections found."
                return result["output"]
            lines = ["File-to-file connections:"]
            for r in results:
                lines.append(
                    f"  {r['source_file']} --[{r['relationship']}]--> {r['target_file']}"
                )
            result["output"] = "\n".join(lines)
            return result["output"]
        finally:
            await store.close()
