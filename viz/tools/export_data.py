"""Export embedding data from pgvector into formats for visualization tools.

Outputs:
  - embeddings.parquet   (for Embedding Atlas + Spotlight)
  - vectors.tsv          (for TensorBoard Projector)
  - metadata.tsv         (for TensorBoard Projector)

Usage:
  python export_data.py --db-url "postgresql+asyncpg://..." --output-dir /data
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:5432/nullrealm",
)


async def load_embeddings(database_url: str) -> list[dict]:
    """Load all embeddings + metadata from pgvector."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, echo=False)
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
        embedding_str = row[1]
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
    """Reduce embedding dimensions using PaCMAP."""
    import pacmap

    arr = np.array(embeddings, dtype=np.float32)
    n_samples = arr.shape[0]
    n_neighbors = min(10, max(2, n_samples - 1))
    reducer = pacmap.PaCMAP(n_components=n_components, n_neighbors=n_neighbors)
    reduced = reducer.fit_transform(arr)
    logger.info(
        "Reduced %d embeddings from %d-d to %d-d via PaCMAP",
        n_samples, arr.shape[1], n_components,
    )
    return reduced


def export_parquet(records: list[dict], coords_2d: np.ndarray, output_dir: Path):
    """Export as parquet for Embedding Atlas and Spotlight."""
    embeddings = [r["embedding"] for r in records]

    df = pd.DataFrame(
        {
            "text": [r["chunk_text"][:500] for r in records],
            "repo": [r["repo"] for r in records],
            "file_path": [r["file_path"] for r in records],
            "module": [str(PurePosixPath(r["file_path"]).parent) for r in records],
            "symbol_name": [r["symbol_name"] for r in records],
            "symbol_type": [r["symbol_type"] for r in records],
            "line_start": [r["line_start"] for r in records],
            "line_end": [r["line_end"] for r in records],
            "x": coords_2d[:, 0].tolist(),
            "y": coords_2d[:, 1].tolist(),
            "embedding": embeddings,
        }
    )

    path = output_dir / "embeddings.parquet"
    df.to_parquet(path, index=False)
    logger.info("Wrote %s (%d rows)", path, len(df))
    return df


def export_tsv(records: list[dict], output_dir: Path):
    """Export as TSV files for TensorBoard Projector."""
    vectors_path = output_dir / "vectors.tsv"
    metadata_path = output_dir / "metadata.tsv"

    # Write vectors (tab-separated, no header)
    with open(vectors_path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        for r in records:
            writer.writerow(r["embedding"])

    # Write metadata (tab-separated, with header)
    with open(metadata_path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["label", "file_path", "symbol_name", "symbol_type", "module"])
        for r in records:
            module = str(PurePosixPath(r["file_path"]).parent)
            label = f"{r['symbol_type']}:{r['symbol_name']}"
            writer.writerow([label, r["file_path"], r["symbol_name"], r["symbol_type"], module])

    logger.info("Wrote %s and %s (%d rows)", vectors_path, metadata_path, len(records))


def export_projector_config(output_dir: Path):
    """Write the TensorBoard Projector config JSON."""
    config = {
        "embeddings": [
            {
                "tensorName": "Code Embeddings (768-dim)",
                "tensorShape": [48, 768],
                "tensorPath": "data/vectors.tsv",
                "metadataPath": "data/metadata.tsv",
            }
        ]
    }
    path = output_dir / "projector_config.json"
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
    logger.info("Wrote %s", path)


async def main():
    parser = argparse.ArgumentParser(description="Export embeddings for viz tools")
    parser.add_argument(
        "--db-url", default=DATABASE_URL,
        help="PostgreSQL async connection URL",
    )
    parser.add_argument(
        "--output-dir", default="/data",
        help="Output directory for exported files",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = await load_embeddings(args.db_url)
    if not records:
        logger.error("No embeddings found in database!")
        sys.exit(1)

    embeddings = [r["embedding"] for r in records]
    coords_2d = reduce_dimensions(embeddings, n_components=2)

    export_parquet(records, coords_2d, output_dir)
    export_tsv(records, output_dir)
    export_projector_config(output_dir)

    logger.info("All exports complete in %s", output_dir)


if __name__ == "__main__":
    asyncio.run(main())
