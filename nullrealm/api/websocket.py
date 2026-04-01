"""WebSocket endpoint for chat communication."""

from fastapi import WebSocket, WebSocketDisconnect

from nullrealm.api.schemas import ChatMessage


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Handle WebSocket connections for chat sessions."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            msg = ChatMessage.model_validate_json(data)
            # Echo for now — agent integration in 02-02
            response = ChatMessage(
                type="assistant_message",
                content=f"Echo: {msg.content}",
                session_id=session_id,
            )
            await websocket.send_text(response.model_dump_json())
    except WebSocketDisconnect:
        pass
