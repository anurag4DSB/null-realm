"""Null Realm MCP Server.

Exposes Graph RAG tools (pgvector search + Neo4j queries) over:
  - Streamable HTTP at /mcp (default, for remote Claude Code / MCP clients)
  - stdio transport (--stdio flag, for local Claude Code)

OAuth endpoints live alongside the MCP mount so the server handles its own
Google OAuth flow without needing an external oauth2-proxy.

Usage:
    # Remote (Streamable HTTP on port 8090)
    python -m nullrealm.mcp_server --port 8090

    # Local (stdio, for Claude Code)
    python -m nullrealm.mcp_server --stdio
"""

import argparse
import contextlib
import logging
import os
import pathlib
import sys

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from nullrealm.mcp_auth import (
    create_mcp_token,
    exchange_code,
    get_authorize_url,
    get_user_email,
    verify_mcp_token,
)
from nullrealm.mcp_tools import (
    do_code_search,
    do_graph_path,
    do_graph_query,
    do_service_map,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP server (tools + resources)
# ---------------------------------------------------------------------------

# Allow the nip.io domain used for GKE ingress (and localhost for dev).
# Entries ending in ":*" match any port (e.g. localhost:8090, localhost:8091).
_allowed_hosts = os.getenv(
    "MCP_ALLOWED_HOSTS",
    "hopocalypse.34.53.165.155.nip.io,localhost:*,127.0.0.1:*",
).split(",")

mcp = FastMCP(
    "null-realm",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[h.strip() for h in _allowed_hosts],
    ),
)

REPO_INDEX_PATH = pathlib.Path(__file__).resolve().parent.parent / "repo-indexes" / "null-realm" / "REPO_INDEX.md"


@mcp.tool()
async def code_search(query: str, repo: str = "null-realm", k: int = 10) -> str:
    """Search code semantically across repositories.

    Embeds the query and returns the top-k most similar code chunks from
    the pgvector store, ranked by cosine similarity.
    """
    return await do_code_search(query, repo=repo, k=k)


@mcp.tool()
async def graph_query(symbol: str, depth: int = 2) -> str:
    """Find connected code symbols in the knowledge graph.

    Returns all symbols reachable from *symbol* within *depth* hops in
    the Neo4j code relationship graph.
    """
    return await do_graph_query(symbol, depth=depth)


@mcp.tool()
async def graph_path(source: str, target: str) -> str:
    """Find shortest path between two code symbols.

    Returns the shortest path (up to 5 hops) between *source* and *target*
    symbols in the Neo4j graph.
    """
    return await do_graph_path(source, target)


@mcp.tool()
async def service_map() -> str:
    """Show all file-to-file connections in the codebase.

    Returns cross-file relationships extracted from AST analysis, useful
    for understanding the architecture and dependency structure.
    """
    return await do_service_map()


@mcp.resource("repo://null-realm/index")
async def repo_index() -> str:
    """REPO_INDEX.md -- architecture summary of null-realm."""
    if REPO_INDEX_PATH.exists():
        return REPO_INDEX_PATH.read_text()
    return "REPO_INDEX.md not found."


# ---------------------------------------------------------------------------
# FastAPI app (OAuth endpoints + MCP mount)
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the MCP session manager lifecycle."""
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Null Realm MCP Server",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health check ---------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-server"}


# --- OAuth endpoints ------------------------------------------------------

@app.get("/oauth/authorize")
async def authorize():
    """Redirect the user to Google's OAuth2 consent screen."""
    url = await get_authorize_url()
    return RedirectResponse(url)


@app.get("/oauth/callback")
async def callback(code: str = Query(...)):
    """Handle the Google OAuth2 callback, exchange code for MCP JWT."""
    try:
        google_tokens = await exchange_code(code)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Google token exchange failed: {exc.response.text}",
        ) from exc

    access_token = google_tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token from Google")

    try:
        email = await get_user_email(access_token)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch user info: {exc.response.text}",
        ) from exc

    mcp_token = create_mcp_token(email)
    logger.info("Issued MCP token for %s", email)
    return {"access_token": mcp_token, "token_type": "bearer", "email": email}


@app.get("/oauth/verify")
async def verify(request: Request):
    """Verify an MCP JWT from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = verify_mcp_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc
    return {"valid": True, "email": payload.get("email")}


# --- Mount MCP at /mcp ----------------------------------------------------

app.mount("/mcp", mcp.streamable_http_app())


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Null Realm MCP Server")
    parser.add_argument("--stdio", action="store_true", help="Run with stdio transport (for local Claude Code)")
    parser.add_argument("--port", type=int, default=8090, help="HTTP port (default: 8090)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.stdio:
        logger.info("Starting MCP server in stdio mode")
        mcp.run(transport="stdio")
    else:
        logger.info("Starting MCP server on %s:%d", args.host, args.port)
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        )


if __name__ == "__main__":
    main()
