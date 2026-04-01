"""Chainlit chat UI for Null Realm, connected to FastAPI WebSocket backend."""

import asyncio
import json
import logging
import os

import chainlit as cl
import websockets

logger = logging.getLogger(__name__)

API_URL = os.getenv("API_WS_URL", "ws://localhost:8000/ws")


@cl.on_chat_start
async def on_chat_start():
    """Open a persistent WebSocket connection for the session."""
    session_id = cl.user_session.get("id")
    cl.user_session.set("session_id", session_id)

    # Open WebSocket once per session — reuse for all messages
    ws = await websockets.connect(f"{API_URL}/{session_id}")
    cl.user_session.set("ws", ws)


@cl.on_chat_end
async def on_chat_end():
    """Close WebSocket when session ends."""
    ws = cl.user_session.get("ws")
    if ws:
        await ws.close()


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")
    ws = cl.user_session.get("ws")

    # Reconnect if WebSocket was closed
    try:
        ws_is_closed = ws is None or not ws.protocol
    except Exception:
        ws_is_closed = True
    if ws_is_closed:
        ws = await websockets.connect(f"{API_URL}/{session_id}")
        cl.user_session.set("ws", ws)

    # Send message
    msg = {
        "type": "user_message",
        "content": message.content,
        "session_id": session_id,
    }
    await ws.send(json.dumps(msg))

    # Create a streaming message for incremental display
    response_msg = cl.Message(content="")
    await response_msg.send()

    active_steps: dict[str, cl.Step] = {}
    complete = False

    while not complete:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            data = json.loads(raw)
            event_type = data.get("type", "")

            if event_type == "text_delta":
                await response_msg.stream_token(data.get("content", ""))

            elif event_type == "tool_use":
                tool_name = data.get("tool", "tool")
                tool_input = data.get("input", {})
                step = cl.Step(name=tool_name, type="tool")
                step.input = json.dumps(tool_input, indent=2)
                await step.send()
                active_steps[tool_name] = step

            elif event_type == "tool_result":
                tool_name = data.get("tool", "tool")
                output = data.get("output", "")
                step = active_steps.pop(tool_name, None)
                if step:
                    step.output = output
                    await step.update()

            elif event_type == "task_complete":
                complete = True

            elif event_type == "assistant_message":
                response_msg.content = data.get("content", "")
                await response_msg.update()
                complete = True

        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for response")
            response_msg.content += "\n\n[Response timed out]"
            break
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            break
        except Exception:
            logger.exception("Error receiving WebSocket message")
            break

    # Finalize streaming message
    await response_msg.update()
