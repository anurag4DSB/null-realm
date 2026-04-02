"""Embedding generation with Vertex AI (production) or sentence-transformers (local dev)."""

import logging
import os

logger = logging.getLogger(__name__)

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
_VERTEX_BATCH_SIZE = 250


def _use_vertex_ai() -> bool:
    """Return True if we should use Vertex AI for embeddings."""
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    # Detect GKE by checking for the metadata server env var
    if os.getenv("KUBERNETES_SERVICE_HOST") and os.getenv("GOOGLE_CLOUD_PROJECT"):
        return True
    return False


def _embed_vertex(texts: list[str]) -> list[list[float]]:
    """Embed via Vertex AI text-embedding-005 (768 dims)."""
    from vertexai.language_models import TextEmbeddingModel

    model = TextEmbeddingModel.from_pretrained("text-embedding-005")
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), _VERTEX_BATCH_SIZE):
        batch = texts[i : i + _VERTEX_BATCH_SIZE]
        embeddings = model.get_embeddings(batch)
        all_embeddings.extend([e.values for e in embeddings])

    return all_embeddings


def _embed_local(texts: list[str]) -> list[list[float]]:
    """Embed via sentence-transformers all-mpnet-base-v2 (768 dims)."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-mpnet-base-v2")
    embeddings = model.encode(texts, show_progress_bar=len(texts) > 50)
    return embeddings.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts, auto-selecting backend.

    Returns a list of float vectors, one per input text.
    Vertex AI is used when GOOGLE_APPLICATION_CREDENTIALS is set or running on GKE;
    otherwise falls back to sentence-transformers (all-mpnet-base-v2, 768 dims).
    """
    if not texts:
        return []

    if _use_vertex_ai():
        logger.info("Using Vertex AI text-embedding-005 for %d texts", len(texts))
        try:
            return _embed_vertex(texts)
        except Exception:
            logger.warning("Vertex AI embedding failed, falling back to sentence-transformers")
            return _embed_local(texts)
    else:
        logger.info("Using sentence-transformers (all-mpnet-base-v2) for %d texts", len(texts))
        return _embed_local(texts)
