"""MCP tool implementations wrapping pgvector and Neo4j stores.

These functions are the shared implementation used by both the MCP server
(exposed over Streamable HTTP / SSE) and the LangGraph builtin tools.
"""

import logging

from nullrealm.context.neo4j_store import Neo4jStore
from nullrealm.context.pgvector_store import PgVectorStore

logger = logging.getLogger(__name__)


async def do_code_search(query: str, repo: str = "null-realm", k: int = 10) -> str:
    """Embed *query* and return the top-k semantically similar code chunks."""
    store = PgVectorStore()
    try:
        await store.init()
        results = await store.search(query, k=k)
        if not results:
            return "No results found."
        formatted = []
        for r in results:
            formatted.append(
                f"[{r['score']:.3f}] {r['file_path']}:{r['symbol_name']}"
                f" ({r['symbol_type']})\n```\n{r['chunk_text'][:500]}\n```"
            )
        return "\n\n".join(formatted)
    finally:
        await store.close()


async def do_graph_query(symbol: str, depth: int = 2) -> str:
    """Find all symbols connected to *symbol* within *depth* hops in Neo4j."""
    store = Neo4jStore()
    try:
        results = await store.query_neighbors(symbol, depth)
        if not results:
            return f"No neighbors found for symbol '{symbol}'."
        lines = [f"Neighbors of '{symbol}' (depth={depth}):"]
        for r in results:
            lines.append(
                f"  [{r['distance']}] {r['file']}:{r['name']} ({r.get('type', 'unknown')})"
            )
        return "\n".join(lines)
    finally:
        await store.close()


async def do_graph_path(source: str, target: str) -> str:
    """Find the shortest path between two symbols in the code graph."""
    store = Neo4jStore()
    try:
        results = await store.query_path(source, target)
        if not results:
            return f"No path found between '{source}' and '{target}'."
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
        return "\n".join(lines)
    finally:
        await store.close()


async def do_service_map() -> str:
    """Return all file-to-file connections in the codebase graph."""
    store = Neo4jStore()
    try:
        results = await store.query_service_map()
        if not results:
            return "No cross-file connections found."
        lines = ["File-to-file connections:"]
        for r in results:
            lines.append(
                f"  {r['source_file']} --[{r['relationship']}]--> {r['target_file']}"
            )
        return "\n".join(lines)
    finally:
        await store.close()
