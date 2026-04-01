"""Health and status endpoints."""

from fastapi import APIRouter

from nullrealm import __version__

router = APIRouter()


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/api/v1/status")
async def status():
    """Detailed status endpoint."""
    return {
        "status": "ok",
        "version": __version__,
        "services": {"websocket": "active"},
    }
