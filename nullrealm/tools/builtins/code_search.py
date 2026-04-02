"""LangChain tool wrapper for semantic code search via pgvector.

This is the LangGraph-native version of the code_search MCP tool.
LangGraph agents call this directly (no MCP transport overhead).
"""

from langchain_core.tools import tool

from nullrealm.mcp_tools import do_code_search


@tool
async def code_search(query: str, repo: str = "null-realm", k: int = 10) -> str:
    """Search code semantically across repositories.

    Embeds the query and returns the top-k most similar code chunks from
    the pgvector store, ranked by cosine similarity.

    Args:
        query: Natural language search query.
        repo: Repository to search (default: null-realm).
        k: Number of results to return (default: 10).
    """
    return await do_code_search(query, repo=repo, k=k)
