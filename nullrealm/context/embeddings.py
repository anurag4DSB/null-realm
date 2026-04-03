"""Embedding generation via LiteLLM (primary), Vertex AI, or sentence-transformers (fallback)."""

import logging
import os

logger = logging.getLogger(__name__)

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


LITELLM_BATCH_SIZE = 5  # Vertex AI text-embedding-005 has a 20K token/request limit; code chunks can be large


def _embed_litellm(texts: list[str]) -> list[list[float]]:
    """Embed via LiteLLM proxy's OpenAI-compatible embedding endpoint.

    Batches requests to avoid exceeding Vertex AI's per-request limits.
    """
    import httpx

    litellm_url = os.getenv("LITELLM_URL", "http://litellm.null-realm.svc.cluster.local:4000/v1")
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), LITELLM_BATCH_SIZE):
        batch = texts[i : i + LITELLM_BATCH_SIZE]
        logger.info("Embedding batch %d-%d of %d", i, i + len(batch), len(texts))
        resp = httpx.post(
            f"{litellm_url}/embeddings",
            json={"model": "text-embedding-005", "input": batch},
            headers={"Authorization": "Bearer not-needed"},
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"LiteLLM embedding failed: {resp.status_code} {resp.text}")
        data = resp.json()
        all_embeddings.extend(item["embedding"] for item in data["data"])

    return all_embeddings


_local_model = None


def _embed_local(texts: list[str]) -> list[list[float]]:
    """Embed via sentence-transformers all-mpnet-base-v2 (768 dims).
    Model is loaded once and cached — avoids re-downloading on every call."""
    global _local_model
    from sentence_transformers import SentenceTransformer

    if _local_model is None:
        logger.info("Loading sentence-transformers model (first call, may take a moment)...")
        _local_model = SentenceTransformer("all-mpnet-base-v2")
    embeddings = _local_model.encode(texts, show_progress_bar=len(texts) > 50)
    return embeddings.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts, auto-selecting backend.

    Priority:
    1. LiteLLM proxy (if LITELLM_URL is set — no model download needed)
    2. sentence-transformers (local fallback — needs 500MB model download)
    """
    if not texts:
        return []

    litellm_url = os.getenv("LITELLM_URL")
    if litellm_url:
        logger.info("Using LiteLLM for %d texts", len(texts))
        try:
            return _embed_litellm(texts)
        except Exception:
            logger.warning("LiteLLM embedding failed, falling back to sentence-transformers", exc_info=True)

    logger.info("Using sentence-transformers (all-mpnet-base-v2) for %d texts", len(texts))
    return _embed_local(texts)
