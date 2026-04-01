"""WebSocket endpoint for chat with direct LangGraph streaming."""

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from nullrealm.api.schemas import ChatMessage
from nullrealm.orchestrator.workflow_executor import WorkflowExecutor
from nullrealm.registry.database import async_session
from nullrealm.registry.models import Workflow
from nullrealm.worker.langgraph_agent import _get_agent, run_agent

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Handle WebSocket connections with direct streaming from LangGraph."""
    await websocket.accept()
    logger.info("WebSocket accepted for session %s", session_id)

    try:
        while True:
            data = await websocket.receive_text()
            parsed = json.loads(data)
            msg_type = parsed.get("type", "user_message")

            if msg_type == "workflow_request":
                await _handle_workflow_request(websocket, parsed, session_id)
                continue

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


async def _handle_workflow_request(websocket: WebSocket, parsed: dict, session_id: str):
    """Handle a workflow execution request over WebSocket."""
    workflow_name = parsed.get("workflow", "feature_development")
    user_input = parsed.get("content", "")

    logger.info(
        "Workflow request: name=%s, session=%s, input=%s",
        workflow_name, session_id, user_input[:80],
    )

    # Look up workflow from registry
    async with async_session() as db:
        result = await db.execute(select(Workflow).where(Workflow.name == workflow_name))
        workflow = result.scalar_one_or_none()

    if not workflow:
        await websocket.send_text(json.dumps({
            "type": "assistant_message",
            "content": f"Workflow '{workflow_name}' not found in registry.",
            "session_id": session_id,
        }))
        return

    steps = workflow.steps
    config = {
        "name": workflow.name,
        "steps": steps,
        "max_parallel_agents": workflow.max_parallel_agents,
    }

    # Notify client of workflow start
    await websocket.send_text(json.dumps({
        "type": "workflow_start",
        "workflow": workflow_name,
        "total_steps": len(steps),
        "session_id": session_id,
    }))

    executor = WorkflowExecutor()
    context = user_input

    for i, step in enumerate(steps):
        step_name = step["name"]
        assistant = step["assistant"]
        description = step.get("description", "")

        # Notify step start
        await websocket.send_text(json.dumps({
            "type": "step_start",
            "step": step_name,
            "assistant": assistant,
            "description": description,
            "step_number": i + 1,
            "total_steps": len(steps),
            "session_id": session_id,
        }))

        # Build task input
        if i == 0:
            task_input = user_input
        else:
            task_input = f"Original request: {user_input}\n\nPrevious step results:\n{context}"

        msg_id = f"{session_id}-step-{i}-{step_name}"

        try:
            workflow_id = await executor.argo.submit_workflow(
                template_name="agent-worker",
                params={
                    "assistant_name": assistant,
                    "session_id": session_id,
                    "task_input": task_input,
                    "msg_id": msg_id,
                },
            )

            # Poll for completion
            status = {"phase": "Unknown"}
            for _ in range(120):
                status = await executor.argo.get_workflow_status(workflow_id)
                if status["phase"] in ("Succeeded", "Failed", "Error"):
                    break
                await asyncio.sleep(1)

            step_status = status["phase"]
            if step_status != "Succeeded":
                context = f"[Step {step_name} failed]"
            else:
                context = f"Step '{step_name}' completed successfully."

        except Exception:
            logger.exception("Failed to execute step %s", step_name)
            step_status = "Error"
            context = f"[Step {step_name} errored]"

        # Notify step complete
        await websocket.send_text(json.dumps({
            "type": "step_complete",
            "step": step_name,
            "status": step_status,
            "session_id": session_id,
        }))

    # Notify workflow complete
    await websocket.send_text(json.dumps({
        "type": "workflow_complete",
        "workflow": workflow_name,
        "session_id": session_id,
    }))


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
                    # Split into characters for smooth streaming
                    for char in content:
                        chunk_count += 1
                        await websocket.send_text(json.dumps({
                            "type": "text_delta",
                            "content": char,
                            "session_id": session_id,
                        }))
                        await asyncio.sleep(0.008)
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
