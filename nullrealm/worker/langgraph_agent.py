"""LangGraph ReAct agent for Null Realm."""

import os
from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

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
