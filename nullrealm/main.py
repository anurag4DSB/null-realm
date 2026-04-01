"""FastAPI application entry point for Null Realm API."""

from fastapi import FastAPI

app = FastAPI(
    title="Null Realm API",
    version="0.1.0",
    description="Multi-agent learning lab on Kubernetes",
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
