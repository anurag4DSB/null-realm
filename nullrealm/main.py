"""FastAPI application entry point for Null Realm API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nullrealm.api.routes.health import router as health_router
from nullrealm.api.websocket import websocket_endpoint
from nullrealm.observability.tracing import init_tracing


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    init_tracing()
    yield


app = FastAPI(
    title="Null Realm API",
    version="0.1.0",
    description="Multi-agent learning lab on Kubernetes",
    lifespan=lifespan,
)

# CORS middleware — allow all origins for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health and status routes
app.include_router(health_router)

# WebSocket route
app.add_api_websocket_route("/ws/{session_id}", websocket_endpoint)
