"""Worker entry point — connects to NATS and processes agent tasks."""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Start the agent worker (placeholder)."""
    logger.info("Null Realm worker starting...")
    logger.info("Worker ready. Waiting for tasks... (placeholder)")
    # In future phases, this will connect to NATS and process agent tasks.
    # For now, just keep alive so the container doesn't exit.
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
