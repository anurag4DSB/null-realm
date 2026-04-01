"""Bootstrap the LangGraph agent with configuration."""

import os

from nullrealm.worker.langgraph_agent import create_agent


def create_configured_agent(
    model_name: str = "claude-sonnet",
    system_prompt: str = "You are a helpful AI assistant in the Null Realm platform. You can read files when asked. Be concise and helpful.",
):
    """Create an agent instance configured from environment."""
    litellm_url = os.getenv(
        "LITELLM_URL", "http://litellm.null-realm.svc.cluster.local:4000/v1"
    )
    return create_agent(
        model_name=model_name,
        litellm_url=litellm_url,
        system_prompt=system_prompt,
    )
