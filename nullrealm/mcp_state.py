"""Shared state between MCP middleware and tool functions.

Separated into its own module to avoid circular import issues
between mcp_server.py and mcp_tools.py.
"""

import threading

# The most recently authenticated user email.
# Written by ASGI middleware, read by tool functions.
last_user_email: str = "anonymous"
lock = threading.Lock()


def set_email(email: str) -> None:
    global last_user_email
    with lock:
        last_user_email = email


def get_email() -> str:
    with lock:
        return last_user_email
