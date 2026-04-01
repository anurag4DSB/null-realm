"""Chainlit chat UI for Null Realm, connected to FastAPI WebSocket backend."""

import json
import os

import chainlit as cl
import websockets

API_URL = os.getenv("API_WS_URL", "ws://localhost:8000/ws")


@cl.on_chat_start
async def on_chat_start():
    session_id = cl.user_session.get("id")
    cl.user_session.set("session_id", session_id)


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")

    # Connect to FastAPI WebSocket
    async with websockets.connect(f"{API_URL}/{session_id}") as ws:
        # Send message
        msg = {
            "type": "user_message",
            "content": message.content,
            "session_id": session_id,
        }
        await ws.send(json.dumps(msg))

        # Receive response
        response = await ws.recv()
        data = json.loads(response)

        await cl.Message(content=data["content"]).send()
