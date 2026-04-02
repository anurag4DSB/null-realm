"""Export embeddings for visualization with PaCMAP dimensionality reduction."""

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:5432/nullrealm",
)


async def load_embeddings_from_db(database_url: str | None = None) -> list[dict]:
    """Load all embeddings + metadata from pgvector.

    Returns a list of dicts with keys:
        chunk_text, embedding (as list[float]), repo, file_path,
        symbol_name, symbol_type, line_start, line_end
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = database_url or DATABASE_URL
    engine = create_async_engine(url, echo=False)

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT chunk_text, embedding::text, repo, file_path, "
                    "symbol_name, symbol_type, line_start, line_end "
                    "FROM code_embeddings ORDER BY file_path, line_start"
                )
            )
            rows = result.fetchall()
    finally:
        await engine.dispose()

    records = []
    for row in rows:
        # Parse the pgvector text representation "[0.1,0.2,...]" into a float list
        embedding_str = row[1]  # embedding::text
        embedding = [float(x) for x in embedding_str.strip("[]").split(",")]
        records.append(
            {
                "chunk_text": row[0],
                "embedding": embedding,
                "repo": row[2],
                "file_path": row[3],
                "symbol_name": row[4],
                "symbol_type": row[5],
                "line_start": row[6],
                "line_end": row[7],
            }
        )

    logger.info("Loaded %d embeddings from database", len(records))
    return records


def reduce_dimensions(embeddings: list[list[float]], n_components: int = 2) -> np.ndarray:
    """Reduce embedding dimensions using PaCMAP.

    Args:
        embeddings: List of embedding vectors (each 768-dim).
        n_components: Target dimensionality (2 or 3).

    Returns:
        numpy array of shape (n_samples, n_components).
    """
    import pacmap

    arr = np.array(embeddings, dtype=np.float32)
    n_samples = arr.shape[0]

    # PaCMAP needs at least n_neighbors+1 samples; default n_neighbors=10
    n_neighbors = min(10, max(2, n_samples - 1))
    reducer = pacmap.PaCMAP(n_components=n_components, n_neighbors=n_neighbors)
    reduced = reducer.fit_transform(arr)
    logger.info(
        "Reduced %d embeddings from %d-d to %d-d via PaCMAP",
        n_samples,
        arr.shape[1],
        n_components,
    )
    return reduced
