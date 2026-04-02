"""LangChain tool wrappers for Neo4j code graph queries.

These are the LangGraph-native versions of the graph MCP tools.
LangGraph agents call these directly (no MCP transport overhead).
"""

from langchain_core.tools import tool

from nullrealm.mcp_tools import do_graph_path, do_graph_query, do_service_map


@tool
async def graph_query(symbol: str, depth: int = 2) -> str:
    """Find connected code symbols in the knowledge graph.

    Returns all symbols reachable from *symbol* within *depth* hops in
    the Neo4j code relationship graph.

    Args:
        symbol: The symbol name to search from.
        depth: Maximum hop distance (default: 2).
    """
    return await do_graph_query(symbol, depth=depth)


@tool
async def graph_path(source: str, target: str) -> str:
    """Find shortest path between two code symbols.

    Returns the shortest path (up to 5 hops) between *source* and *target*
    symbols in the Neo4j graph.

    Args:
        source: Starting symbol name.
        target: Ending symbol name.
    """
    return await do_graph_path(source, target)


@tool
async def service_map() -> str:
    """Show all file-to-file connections in the codebase.

    Returns cross-file relationships extracted from AST analysis, useful
    for understanding the architecture and dependency structure.
    """
    return await do_service_map()
