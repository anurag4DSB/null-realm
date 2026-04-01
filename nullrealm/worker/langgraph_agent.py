"""LangGraph ReAct agent for Null Realm."""

import logging
import os
from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from nullrealm.communication.events import (
    TaskCompleteEvent,
    TextDeltaEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from nullrealm.communication.nats_bus import NATSBus

logger = logging.getLogger(__name__)

# --- Tool definitions (LangChain format) ---


@tool
def file_read(path: str) -> str:
    """Read the contents of a file given its path."""
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


TOOLS = [file_read]


# --- Agent state ---


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# --- Graph nodes ---


def create_agent(
    model_name: str = "claude-sonnet",
    litellm_url: str | None = None,
    system_prompt: str = "You are a helpful AI assistant in the Null Realm platform. You can read files when asked. Be concise and helpful.",
):
    """Create and return a compiled LangGraph ReAct agent."""

    base_url = litellm_url or os.getenv(
        "LITELLM_URL", "http://litellm.null-realm.svc.cluster.local:4000/v1"
    )

    llm = ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key="not-needed",  # LiteLLM proxy handles auth
        temperature=0.1,
        timeout=120,
        max_retries=2,
    )

    llm_with_tools = llm.bind_tools(TOOLS)

    def call_llm(state: AgentState) -> dict:
        messages = state["messages"]
        # Prepend system prompt if not already present
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def call_tools(state: AgentState) -> dict:
        last_message = state["messages"][-1]
        tool_results = []
        tools_by_name = {t.name: t for t in TOOLS}

        for tool_call in last_message.tool_calls:
            tool_fn = tools_by_name[tool_call["name"]]
            result = tool_fn.invoke(tool_call["args"])
            tool_results.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )

        return {"messages": tool_results}

    def should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return "end"

    # --- Build graph ---
    graph = StateGraph(AgentState)
    graph.add_node("llm", call_llm)
    graph.add_node("tools", call_tools)
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "llm")

    return graph.compile()


_cached_agent = None


def _get_agent(litellm_url: str | None = None):
    """Return a cached agent instance (singleton)."""
    global _cached_agent
    if _cached_agent is None:
        _cached_agent = create_agent(litellm_url=litellm_url)
    return _cached_agent


async def run_agent(user_message: str, litellm_url: str | None = None) -> str:
    """Run the agent with a single user message and return the final response."""
    agent = _get_agent(litellm_url=litellm_url)
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_message)]}
    )
    # Get the last AI message
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
    return "No response generated."


async def run_agent_streaming(
    user_message: str,
    session_id: str,
    nats_bus: NATSBus | None = None,
    litellm_url: str | None = None,
    msg_id: str = "",
) -> str:
    """Run the agent with streaming, publishing events to NATS.

    Falls back to non-streaming run_agent() if NATS is unavailable.
    """
    # If no NATS bus or not connected, fall back to non-streaming
    if nats_bus is None or not nats_bus.is_connected:
        logger.warning("NATS not available, falling back to non-streaming agent")
        result = await run_agent(user_message, litellm_url=litellm_url)
        return result

    agent = _get_agent(litellm_url=litellm_url)
    full_response = ""

    try:
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=user_message)]},
            version="v2",
        ):
            kind = event.get("event")

            if kind == "on_chat_model_stream":
                # Token-by-token streaming from the LLM
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    content = chunk.content
                    # content can be a string or a list of dicts
                    if isinstance(content, str) and content:
                        full_response += content
                        delta = TextDeltaEvent(
                            session_id=session_id,
                            content=content,
                        )
                        await nats_bus.publish(
                            f"agent.{session_id}.{msg_id}.events",
                            delta.model_dump_json().encode(),
                        )
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "")
                                if text:
                                    full_response += text
                                    delta = TextDeltaEvent(
                                        session_id=session_id,
                                        content=text,
                                    )
                                    await nats_bus.publish(
                                        f"agent.{session_id}.{msg_id}.events",
                                        delta.model_dump_json().encode(),
                                    )

            elif kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                tool_event = ToolUseEvent(
                    session_id=session_id,
                    tool=tool_name,
                    input=tool_input if isinstance(tool_input, dict) else {"input": str(tool_input)},
                )
                await nats_bus.publish(
                    f"agent.{session_id}.{msg_id}.events",
                    tool_event.model_dump_json().encode(),
                )

            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output = event.get("data", {}).get("output", "")
                result_event = ToolResultEvent(
                    session_id=session_id,
                    tool=tool_name,
                    output=str(output),
                )
                await nats_bus.publish(
                    f"agent.{session_id}.{msg_id}.events",
                    result_event.model_dump_json().encode(),
                )

        # Publish completion event
        complete = TaskCompleteEvent(
            session_id=session_id,
            result=full_response or "No response generated.",
        )
        await nats_bus.publish(
            f"done.{session_id}.{msg_id}",
            complete.model_dump_json().encode(),
        )

    except Exception:
        logger.exception("Error during streaming agent run, publishing completion")
        # Still send a completion event so the WebSocket doesn't hang
        if not full_response:
            full_response = await run_agent(user_message, litellm_url=litellm_url)
        complete = TaskCompleteEvent(
            session_id=session_id,
            result=full_response,
        )
        try:
            await nats_bus.publish(
                f"done.{session_id}.{msg_id}",
                complete.model_dump_json().encode(),
            )
        except Exception:
            logger.exception("Failed to publish completion event after error")

    return full_response
