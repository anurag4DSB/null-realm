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


async def _ensure_ws(session_id: str):
    """Ensure the WebSocket is connected, reconnecting if needed."""
    ws = cl.user_session.get("ws")
    try:
        ws_is_closed = ws is None or not ws.protocol
    except Exception:
        ws_is_closed = True
    if ws_is_closed:
        ws = await websockets.connect(f"{API_URL}/{session_id}")
        cl.user_session.set("ws", ws)
    return ws


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")
    ws = await _ensure_ws(session_id)

    # Check for slash commands
    if message.content.startswith("/workflow "):
        parts = message.content.split(" ", 2)
        workflow_name = parts[1] if len(parts) > 1 else "feature_development"
        user_input = parts[2] if len(parts) > 2 else ""
        await _handle_workflow(workflow_name, user_input, session_id, ws)
    elif message.content.startswith("/context "):
        query = message.content[len("/context "):].strip()
        await _handle_context(query, session_id, ws)
    else:
        await _handle_chat(message, session_id, ws)


async def _handle_chat(message: cl.Message, session_id: str, ws):
    """Handle a regular chat message with streaming response."""
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


async def _handle_workflow(workflow_name: str, user_input: str, session_id: str, ws):
    """Handle a workflow execution with step visualization."""
    # Send workflow request to API server via WebSocket
    msg = {
        "type": "workflow_request",
        "workflow": workflow_name,
        "content": user_input,
        "session_id": session_id,
    }
    await ws.send(json.dumps(msg))

    # Create a parent message for the workflow
    response_msg = cl.Message(content=f"Starting workflow: **{workflow_name}**\n\n")
    await response_msg.send()

    active_steps: dict[str, cl.Step] = {}
    complete = False

    while not complete:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=180)
            data = json.loads(raw)
            event_type = data.get("type", "")

            if event_type == "workflow_start":
                total = data.get("total_steps", 0)
                await response_msg.stream_token(
                    f"Workflow has {total} steps. Executing sequentially...\n\n"
                )

            elif event_type == "step_start":
                step_name = data.get("step", "unknown")
                assistant = data.get("assistant", "unknown")
                description = data.get("description", "")
                step_num = data.get("step_number", 0)
                total = data.get("total_steps", 0)

                step = cl.Step(name=f"Step {step_num}: {step_name}", type="run")
                step.input = f"Assistant: {assistant}\n{description}"
                await step.send()
                active_steps[step_name] = step

                await response_msg.stream_token(
                    f"**Step {step_num}/{total}: {step_name}** ({assistant}) - Running...\n"
                )

            elif event_type == "step_complete":
                step_name = data.get("step", "unknown")
                status = data.get("status", "unknown")
                step = active_steps.pop(step_name, None)
                if step:
                    step.output = f"Status: {status}"
                    await step.update()

                icon = "[ok]" if status == "Succeeded" else "[fail]"
                await response_msg.stream_token(f"  {icon} {step_name}: {status}\n\n")

            elif event_type == "text_delta":
                # Forward streaming text from agent steps
                await response_msg.stream_token(data.get("content", ""))

            elif event_type == "workflow_complete":
                await response_msg.stream_token("\nWorkflow complete.")
                complete = True

            elif event_type == "assistant_message":
                # Error or info message
                await response_msg.stream_token(data.get("content", ""))
                complete = True

        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for workflow response")
            await response_msg.stream_token("\n\n[Workflow timed out]")
            break
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed during workflow")
            break
        except Exception:
            logger.exception("Error receiving workflow WebSocket message")
            break

    # Finalize
    await response_msg.update()


async def _handle_context(query: str, session_id: str, ws):
    """Handle /context command: run context assembler and show results as steps."""
    msg = {
        "type": "context_request",
        "content": query,
        "session_id": session_id,
    }
    await ws.send(json.dumps(msg))

    response_msg = cl.Message(
        content=f"Assembling context for: **{query}**\n\n"
    )
    await response_msg.send()

    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        data = json.loads(raw)

        if data.get("type") != "context_result":
            await response_msg.stream_token(
                f"Unexpected response: {data.get('type', 'unknown')}"
            )
            await response_msg.update()
            return

        results = data.get("results", {})

        if "error" in results:
            await response_msg.stream_token(f"Error: {results['error']}")
            await response_msg.update()
            return

        # Step 1: REPO_INDEX summary
        repo_summary = results.get("repo_summary", "")
        if repo_summary:
            step = cl.Step(name="REPO_INDEX", type="tool")
            step.output = repo_summary
            await step.send()

        # Step 2: Vector search results
        vector_results = results.get("vector_results", [])
        if vector_results:
            step = cl.Step(name="Vector Search", type="tool")
            lines = []
            for r in vector_results:
                score = r.get("score", 0)
                fp = r.get("file_path", "?")
                sym = r.get("symbol_name", "?")
                stype = r.get("symbol_type", "?")
                chunk = r.get("chunk_text", "")[:200]
                lines.append(
                    f"**[{score:.3f}]** `{fp}:{sym}` ({stype})\n"
                    f"```\n{chunk}\n```"
                )
            step.output = "\n\n".join(lines)
            await step.send()

        # Step 3: Graph expansion results
        graph_paths = results.get("graph_paths", [])
        if graph_paths:
            step = cl.Step(name="Graph Expansion", type="tool")
            lines = []
            for g in graph_paths:
                lines.append(
                    f"- `{g.get('file', '?')}:{g.get('name', '?')}` "
                    f"({g.get('type', '?')}, distance={g.get('distance', '?')})"
                )
            step.output = "\n".join(lines)
            await step.send()

        # Summary line
        total_tokens = results.get("total_tokens", 0)
        n_vector = len(vector_results)
        n_graph = len(graph_paths)
        has_index = "yes" if repo_summary else "no"
        await response_msg.stream_token(
            f"Context assembled: {n_vector} vector results, "
            f"{n_graph} graph connections, "
            f"REPO_INDEX: {has_index}, "
            f"~{total_tokens} tokens"
        )

    except asyncio.TimeoutError:
        await response_msg.stream_token("\n\n[Context assembly timed out]")
    except websockets.exceptions.ConnectionClosed:
        logger.warning("WebSocket closed during context request")
    except Exception:
        logger.exception("Error during context request")
        await response_msg.stream_token("\n\n[Error during context assembly]")

    await response_msg.update()
