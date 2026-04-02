"""Hybrid context assembly: vector search + graph expansion."""

import logging
import os
import pathlib
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AssembledContext:
    repo_summary: str = ""
    vector_results: list = field(default_factory=list)
    graph_paths: list = field(default_factory=list)
    total_tokens: int = 0

    def to_prompt_context(self) -> str:
        """Format assembled context for inclusion in agent system prompt."""
        parts = []
        if self.repo_summary:
            parts.append(f"## Repository Overview\n{self.repo_summary[:2000]}")
        if self.vector_results:
            parts.append("## Relevant Code (semantic search)")
            for r in self.vector_results[:5]:
                parts.append(
                    f"### {r['file_path']}:{r['symbol_name']} "
                    f"(score: {r['score']:.3f})"
                )
                parts.append(f"```\n{r['chunk_text'][:500]}\n```")
        if self.graph_paths:
            parts.append("## Related Code (graph connections)")
            for g in self.graph_paths[:10]:
                parts.append(
                    f"- {g.get('file', '?')}:{g.get('name', '?')} "
                    f"({g.get('type', '?')}, distance={g.get('distance', '?')})"
                )
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        """Serialise to a dict suitable for JSON transport over WebSocket."""
        return {
            "repo_summary": self.repo_summary[:500],
            "vector_results": [
                {
                    "file_path": r.get("file_path", ""),
                    "symbol_name": r.get("symbol_name", ""),
                    "symbol_type": r.get("symbol_type", ""),
                    "score": r.get("score", 0),
                    "chunk_text": r.get("chunk_text", "")[:300],
                }
                for r in self.vector_results[:5]
            ],
            "graph_paths": [
                {
                    "file": g.get("file", "?"),
                    "name": g.get("name", "?"),
                    "type": g.get("type", "?"),
                    "distance": g.get("distance", "?"),
                }
                for g in self.graph_paths[:10]
            ],
            "total_tokens": self.total_tokens,
        }


class ContextAssembler:
    """Assemble hybrid context from pgvector + Neo4j for a given task."""

    def __init__(self):
        self._pgvector = None
        self._neo4j = None

    async def _get_pgvector(self):
        if self._pgvector is None:
            from nullrealm.context.pgvector_store import PgVectorStore

            self._pgvector = PgVectorStore()
            await self._pgvector.init()
        return self._pgvector

    async def _get_neo4j(self):
        if self._neo4j is None:
            neo4j_uri = os.getenv("NEO4J_URI")
            if neo4j_uri:
                from nullrealm.context.neo4j_store import Neo4jStore

                self._neo4j = Neo4jStore()
        return self._neo4j

    async def assemble(
        self, task: str, repos: list[str] | None = None
    ) -> AssembledContext:
        """Assemble context for a task using vector search + graph expansion."""
        ctx = AssembledContext()

        # 1. Load REPO_INDEX.md
        index_path = pathlib.Path("repo-indexes/null-realm/REPO_INDEX.md")
        if index_path.exists():
            ctx.repo_summary = index_path.read_text()

        # 2. Vector search
        try:
            store = await self._get_pgvector()
            ctx.vector_results = await store.search(task, k=5)
            logger.info("Vector search returned %d results", len(ctx.vector_results))
        except Exception:
            logger.warning("Vector search failed", exc_info=True)

        # 3. Graph expansion for top vector hits
        try:
            neo4j = await self._get_neo4j()
            if neo4j and ctx.vector_results:
                for result in ctx.vector_results[:3]:
                    symbol = result.get("symbol_name", "")
                    if symbol:
                        neighbors = await neo4j.query_neighbors(symbol, depth=1)
                        ctx.graph_paths.extend(neighbors)
                logger.info(
                    "Graph expansion found %d related symbols", len(ctx.graph_paths)
                )
        except Exception:
            logger.warning("Graph expansion failed", exc_info=True)

        # Estimate tokens (~4 chars per token)
        ctx.total_tokens = len(ctx.to_prompt_context()) // 4
        return ctx

    async def close(self):
        """Release connections."""
        if self._pgvector:
            await self._pgvector.close()
        if self._neo4j:
            await self._neo4j.close()
