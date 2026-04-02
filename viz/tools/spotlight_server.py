"""Serve embeddings via Renumics Spotlight."""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    data_path = Path("/data/embeddings.parquet")
    if not data_path.exists():
        logger.error("Parquet file not found at %s", data_path)
        sys.exit(1)

    logger.info("Loading data from %s", data_path)
    df = pd.read_parquet(data_path)
    logger.info("Loaded %d rows with columns: %s", len(df), list(df.columns))

    # Spotlight expects the embedding column to be a numpy array per row
    if "embedding" in df.columns:
        df["embedding"] = df["embedding"].apply(lambda x: np.array(x, dtype=np.float32))

    from renumics import spotlight

    logger.info("Starting Spotlight on 0.0.0.0:8080")
    spotlight.show(
        df,
        host="0.0.0.0",
        port=8080,
        no_browser=True,
        no_ssl=True,  # OK — OAuth + Traefik handle security at the edge
        wait="forever",
    )


if __name__ == "__main__":
    main()
