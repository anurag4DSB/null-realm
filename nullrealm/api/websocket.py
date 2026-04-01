"""WebSocket endpoint for chat with direct LangGraph streaming."""

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.messages import AIMessage, HumanMessage

from nullrealm.api.schemas import ChatMessage
from nullrealm.worker.langgraph_agent import _get_agent, run_agent

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Handle WebSocket connections with direct streaming from LangGraph."""
    await websocket.accept()
    logger.info("WebSocket accepted for session %s", session_id)

    try:
        while True:
            data = await websocket.receive_text()
            msg = ChatMessage.model_validate_json(data)
            logger.info("Received message for session %s: %s", session_id, msg.content[:50])

            try:
                await _stream_agent_response(websocket, msg.content, session_id)
                logger.info("Streaming complete for session %s", session_id)
            except Exception:
                logger.exception("Streaming failed for session %s, falling back", session_id)
                try:
                    result = await run_agent(msg.content)
                    response = ChatMessage(
                        type="assistant_message",
                        content=result,
                        session_id=session_id,
                    )
                    await websocket.send_text(response.model_dump_json())
                    logger.info("Fallback response sent for session %s", session_id)
                except Exception:
                    logger.exception("Fallback also failed for session %s", session_id)
                    error = ChatMessage(
                        type="assistant_message",
                        content="Sorry, something went wrong.",
                        session_id=session_id,
                    )
                    await websocket.send_text(error.model_dump_json())

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)


async def _stream_agent_response(
    websocket: WebSocket,
    user_message: str,
    session_id: str,
):
    """Stream agent response directly to WebSocket using LangGraph astream_events."""
    agent = _get_agent()
    logger.info("Starting agent streaming for session %s", session_id)
    chunk_count = 0

    async for event in agent.astream_events(
        {"messages": [HumanMessage(content=user_message)]},
        version="v2",
    ):
        kind = event.get("event")

        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                content = chunk.content
                if isinstance(content, str) and content:
                    chunk_count += 1
                    await websocket.send_text(json.dumps({
                        "type": "text_delta",
                        "content": content,
                        "session_id": session_id,
                    }))
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                await websocket.send_text(json.dumps({
                                    "type": "text_delta",
                                    "content": text,
                                    "session_id": session_id,
                                }))

        elif kind == "on_tool_start":
            await websocket.send_text(json.dumps({
                "type": "tool_use",
                "tool": event.get("name", "unknown"),
                "input": event.get("data", {}).get("input", {}),
                "session_id": session_id,
            }))

        elif kind == "on_tool_end":
            await websocket.send_text(json.dumps({
                "type": "tool_result",
                "tool": event.get("name", "unknown"),
                "output": str(event.get("data", {}).get("output", "")),
                "session_id": session_id,
            }))

    # Signal completion
    logger.info("Streaming complete for session %s (%d chunks sent)", session_id, chunk_count)
    await websocket.send_text(json.dumps({
        "type": "task_complete",
        "session_id": session_id,
    }))
