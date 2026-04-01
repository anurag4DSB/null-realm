"""NATS JetStream messaging client for Null Realm."""

import logging
import os

import nats
from nats.js import JetStreamContext

logger = logging.getLogger(__name__)


class NATSBus:
    def __init__(self):
        self._nc = None
        self._js: JetStreamContext | None = None

    @property
    def is_connected(self) -> bool:
        return self._nc is not None and self._nc.is_connected

    async def connect(self) -> "NATSBus":
        url = os.getenv("NATS_URL", "nats://nats.null-realm.svc.cluster.local:4222")
        self._nc = await nats.connect(url, connect_timeout=5, max_reconnect_attempts=1)
        self._js = self._nc.jetstream()
        # Create stream for agent events
        try:
            await self._js.add_stream(name="AGENT_EVENTS", subjects=["agent.>", "done.>"])
        except Exception:
            pass  # stream already exists
        logger.info("Connected to NATS at %s", url)
        return self

    async def publish(self, subject: str, data: bytes):
        await self._js.publish(subject, data)

    async def subscribe(self, subject: str, callback, durable: str = None):
        return await self._js.subscribe(subject, cb=callback, durable=durable)

    async def close(self):
        if self._nc:
            await self._nc.close()
            logger.info("NATS connection closed")
