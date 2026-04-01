"""Bootstrap an agent from registry config and execute a task."""

import asyncio
import logging
import os

import httpx
from langchain_core.messages import HumanMessage

from nullrealm.communication.events import TaskCompleteEvent, TextDeltaEvent
from nullrealm.communication.nats_bus import NATSBus
from nullrealm.worker.langgraph_agent import create_agent, run_agent

logger = logging.getLogger(__name__)


async def bootstrap_and_run():
    """Load config from registry, create agent, execute task, stream via NATS."""
    assistant_name = os.environ.get("ASSISTANT_NAME", "research")
    session_id = os.environ.get("SESSION_ID", "unknown")
    task_input = os.environ.get("TASK_INPUT", "")
    msg_id = os.environ.get("MSG_ID", "")
    registry_url = os.environ.get(
        "REGISTRY_URL", "http://api-server.null-realm.svc.cluster.local:8000"
    )

    logging.basicConfig(level=logging.INFO)

    # Initialize tracing (OTEL → Jaeger)
    from nullrealm.observability.tracing import init_tracing
    init_tracing()

    logger.info("Bootstrapping agent: %s, session: %s", assistant_name, session_id)

    # Fetch assistant config from registry
    model = "claude-sonnet"
    system_prompt = "You are a helpful assistant."

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{registry_url}/api/v1/registry/assistants/{assistant_name}"
            )
            if resp.status_code == 200:
                config = resp.json()
                model = config.get("model_preference", model)
                system_prompt = config.get("system_prompt", system_prompt)
                logger.info("Loaded assistant config: model=%s", model)
            else:
                logger.warning(
                    "Could not load assistant config (status %s), using defaults",
                    resp.status_code,
                )
        except Exception:
            logger.warning("Could not reach registry, using defaults")

    # Create agent
    agent = create_agent(model_name=model, system_prompt=system_prompt)

    # Connect to NATS if available
    nats_bus = None
    nats_url = os.getenv("NATS_URL")
    if nats_url:
        try:
            nats_bus = NATSBus()
            await nats_bus.connect()
            logger.info("Connected to NATS")
        except Exception:
            logger.warning("Could not connect to NATS, running without streaming")
            nats_bus = None

    # Execute task
    logger.info("Executing task: %s", task_input[:100])

    if nats_bus:
        # Stream via NATS
        event_subject = f"agent.{session_id}.{msg_id}.events"
        done_subject = f"done.{session_id}.{msg_id}"
        full_response = ""

        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=task_input)]},
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if (
                    chunk
                    and hasattr(chunk, "content")
                    and isinstance(chunk.content, str)
                    and chunk.content
                ):
                    full_response += chunk.content
                    delta = TextDeltaEvent(
                        session_id=session_id, content=chunk.content
                    )
                    await nats_bus.publish(
                        event_subject, delta.model_dump_json().encode()
                    )

        complete = TaskCompleteEvent(
            session_id=session_id, result=full_response or "No response."
        )
        await nats_bus.publish(done_subject, complete.model_dump_json().encode())
        await nats_bus.close()
    else:
        # Non-streaming fallback
        result = await run_agent(task_input)
        logger.info("Result: %s", result[:200])

    logger.info("Agent task complete")


if __name__ == "__main__":
    asyncio.run(bootstrap_and_run())
