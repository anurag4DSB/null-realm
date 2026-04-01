"""WebSocket endpoint for chat communication."""

import logging

from fastapi import WebSocket, WebSocketDisconnect

from nullrealm.api.schemas import ChatMessage
from nullrealm.worker.langgraph_agent import run_agent

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Handle WebSocket connections for chat sessions."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            msg = ChatMessage.model_validate_json(data)

            # Run the LangGraph agent
            try:
                agent_response = await run_agent(msg.content)
            except Exception as e:
                logger.exception("Agent error")
                agent_response = f"Agent error: {e}"

            response = ChatMessage(
                type="assistant_message",
                content=agent_response,
                session_id=session_id,
            )
            await websocket.send_text(response.model_dump_json())
    except WebSocketDisconnect:
        pass
