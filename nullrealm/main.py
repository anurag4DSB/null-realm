"""FastAPI application entry point for Null Realm API."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nullrealm.api.routes.health import router as health_router
from nullrealm.api.websocket import websocket_endpoint
from nullrealm.communication.nats_bus import NATSBus
from nullrealm.observability.tracing import init_tracing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    init_tracing()

    # Connect to NATS JetStream
    nats_bus = NATSBus()
    try:
        await nats_bus.connect()
        app.state.nats_bus = nats_bus
        logger.info("NATS bus connected and stored in app state")
    except Exception:
        logger.warning("Could not connect to NATS — streaming disabled, using fallback mode")
        app.state.nats_bus = None

    yield

    # Shutdown: close NATS connection
    if app.state.nats_bus is not None:
        await app.state.nats_bus.close()


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
