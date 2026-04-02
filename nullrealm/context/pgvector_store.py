"""pgvector-backed vector store for code embeddings."""

import logging
import os
import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.types import Uuid

logger = logging.getLogger(__name__)

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:5432/nullrealm",
)

metadata_obj = MetaData()

code_embeddings = Table(
    "code_embeddings",
    metadata_obj,
    Column("id", Uuid, primary_key=True, default=uuid.uuid4),
    Column("chunk_text", Text, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    Column("repo", String(255), nullable=False),
    Column("file_path", String(1024), nullable=False),
    Column("symbol_name", String(512), nullable=False),
    Column("symbol_type", String(50), nullable=False),
    Column("line_start", Integer, nullable=False, default=0),
    Column("line_end", Integer, nullable=False, default=0),
    Column("metadata_", JSONB, nullable=True, key="metadata"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

hnsw_index = Index(
    "ix_code_embeddings_hnsw",
    code_embeddings.c.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},
    postgresql_ops={"embedding": "vector_cosine_ops"},
)


class PgVectorStore:
    """Async pgvector store for code embeddings."""

    def __init__(self, database_url: str | None = None):
        url = database_url or DATABASE_URL
        self._engine = create_async_engine(url, echo=False)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self):
        """Create the pgvector extension and code_embeddings table if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(metadata_obj.create_all)
        logger.info("pgvector store initialized (dim=%d)", EMBEDDING_DIM)

    async def store_embeddings(
        self,
        chunks: list,
        embeddings: list[list[float]],
        repo_name: str = "unknown",
    ):
        """Batch-insert code chunks with their embeddings.

        Args:
            chunks: List of CodeChunk dataclass instances.
            embeddings: Corresponding embedding vectors.
            repo_name: Repository identifier.
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings"
            )

        # Clear existing embeddings for this repo to avoid duplicates on re-index
        async with self._session_factory() as session:
            await session.execute(
                code_embeddings.delete().where(code_embeddings.c.repo == repo_name)
            )
            await session.commit()

        # Batch insert
        batch_size = 100
        async with self._session_factory() as session:
            for i in range(0, len(chunks), batch_size):
                batch_chunks = chunks[i : i + batch_size]
                batch_embeds = embeddings[i : i + batch_size]

                rows = []
                for chunk, emb in zip(batch_chunks, batch_embeds):
                    rows.append(
                        {
                            "id": uuid.uuid4(),
                            "chunk_text": chunk.text[:10000],  # Truncate very large chunks
                            "embedding": emb,
                            "repo": repo_name,
                            "file_path": chunk.file_path,
                            "symbol_name": chunk.symbol_name,
                            "symbol_type": chunk.symbol_type,
                            "line_start": chunk.line_start,
                            "line_end": chunk.line_end,
                            "metadata_": chunk.metadata,
                            "created_at": datetime.now(UTC),
                        }
                    )

                await session.execute(code_embeddings.insert(), rows)
                await session.commit()

            logger.info("Inserted %d embeddings for repo=%s", len(chunks), repo_name)

    async def search(
        self,
        query: str,
        k: int = 10,
        repo: str | None = None,
    ) -> list[dict]:
        """Embed a query string and find the top-k most similar code chunks.

        Args:
            query: Natural language search query.
            k: Number of results to return.
            repo: Optional repo filter.

        Returns:
            List of dicts with keys: score, file_path, symbol_name, symbol_type,
            line_start, line_end, chunk_text, metadata.
        """
        from nullrealm.context.embeddings import embed_texts

        query_embedding = embed_texts([query])[0]

        # Cosine distance: 1 - cosine_similarity; lower = more similar
        distance_expr = code_embeddings.c.embedding.cosine_distance(query_embedding)

        stmt = (
            select(
                code_embeddings.c.file_path,
                code_embeddings.c.symbol_name,
                code_embeddings.c.symbol_type,
                code_embeddings.c.line_start,
                code_embeddings.c.line_end,
                code_embeddings.c.chunk_text,
                code_embeddings.c.metadata,
                distance_expr.label("distance"),
            )
            .order_by(distance_expr)
            .limit(k)
        )

        if repo:
            stmt = stmt.where(code_embeddings.c.repo == repo)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.fetchall()

        return [
            {
                "score": round(1.0 - row.distance, 4),  # Convert distance to similarity
                "file_path": row.file_path,
                "symbol_name": row.symbol_name,
                "symbol_type": row.symbol_type,
                "line_start": row.line_start,
                "line_end": row.line_end,
                "chunk_text": row.chunk_text,
                "metadata": row.metadata,
            }
            for row in rows
        ]

    async def close(self):
        """Dispose of the engine."""
        await self._engine.dispose()
