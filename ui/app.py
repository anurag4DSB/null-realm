"""Minimal Chainlit chat UI for Null Realm."""

import chainlit as cl


@cl.on_message
async def on_message(message: cl.Message):
    """Echo the user's message back (placeholder for agent integration)."""
    await cl.Message(
        content=f"Echo: {message.content}",
    ).send()
