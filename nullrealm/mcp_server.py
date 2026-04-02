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


@mcp.tool()
async def context_assemble(query: str) -> str:
    """Assemble rich context for a query using hybrid Graph RAG.

    Combines three sources:
    1. REPO_INDEX.md — high-level architecture summary
    2. Vector search (pgvector) — semantically similar code chunks
    3. Graph expansion (Neo4j) — symbols connected to the vector hits

    Use this when you need comprehensive codebase understanding for a task,
    not just a single code search. Returns structured context ready to use.
    """
    from nullrealm.context.assembler import ContextAssembler

    assembler = ContextAssembler()
    try:
        ctx = await assembler.assemble(query)
        return ctx.to_prompt_context()
    finally:
        await assembler.close()


@mcp.tool()
async def index_repo(url: str, branch: str = "main", name: str = "") -> str:
    """Clone a Git repo and index it into the knowledge graph.

    Supports private repos via SSH (git@github.com:org/repo.git).
    Public repos use HTTPS. Re-indexing is idempotent — old data is replaced.
    """
    from nullrealm.context.repo_manager import index_repository
    try:
        result = await index_repository(url, branch=branch, repo_name=name)
        return (
            f"Indexed '{result['repo_name']}' from {result['url']}:\n"
            f"  Chunks: {result['chunks']}\n"
            f"  Relationships: {result['relationships']}\n"
            f"  Summary: {result['summary_path'] or 'skipped'}"
        )
    except Exception as e:
        return f"Indexing failed: {e}"


@mcp.tool()
async def delete_repo_index(repo_name: str) -> str:
    """Remove all indexed data for a repository.

    Deletes embeddings from pgvector, nodes from Neo4j, REPO_INDEX.md,
    and cached clone. Use list_repos first to see available repo names.
    """
    from nullrealm.context.repo_manager import delete_repository_index
    result = await delete_repository_index(repo_name)
    return (
        f"Deleted index for '{result['repo_name']}':\n"
        f"  Chunks removed: {result['chunks_deleted']}\n"
        f"  Graph nodes removed: {result['nodes_deleted']}"
    )


@mcp.tool()
async def list_repos() -> str:
    """List all indexed repositories with chunk counts and file stats."""
    from nullrealm.context.repo_manager import list_indexed_repos
    repos = await list_indexed_repos()
    if not repos:
        return "No repositories indexed yet. Use index_repo to add one."
    lines = ["Indexed repositories:\n"]
    for r in repos:
        lines.append(
            f"  {r['repo']}:\n"
            f"    Chunks: {r['chunks']}, Files: {r['files']}\n"
            f"    First indexed: {r.get('first_indexed', 'unknown')}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------

@mcp.resource("repo://null-realm/index")
async def repo_index() -> str:
    """REPO_INDEX.md -- architecture summary of null-realm."""
    if REPO_INDEX_PATH.exists():
        return REPO_INDEX_PATH.read_text()
    return "REPO_INDEX.md not found."


@mcp.resource("null-realm://services")
async def service_urls() -> str:
    """All deployed null-realm service URLs and what they do."""
    return """# Null Realm Services

## Chat & AI
| Service | URL | Purpose |
|---------|-----|---------|
| Chat (Chainlit) | http://chat.34.53.165.155.nip.io | Chat with Claude via LangGraph agent |
| MCP Server (Hopocalypse) | http://hopocalypse.34.53.165.155.nip.io/mcp | MCP tools: code_search, graph_query, index_repo, list_repos |
| API Server | http://api.34.53.165.155.nip.io | REST API: /health, /api/v1/registry/*, /api/v1/workflows/* |

## Observability
| Service | URL | Purpose |
|---------|-----|---------|
| Langfuse | http://34.53.165.155.nip.io | LLM traces (tokens, cost, latency) |
| Grafana | http://grafana.34.53.165.155.nip.io | Dashboards: K8s, Argo Workflows, Code Knowledge Graph |
| Jaeger | http://jaeger.34.53.165.155.nip.io | Distributed traces (OpenTelemetry spans) |
| Argo Workflows | http://argo.34.53.165.155.nip.io | Multi-agent workflow orchestration UI |

## Code Intelligence
| Service | URL | Purpose |
|---------|-----|---------|
| Embedding Explorer | http://embeddings.34.53.165.155.nip.io | 2D/3D scatter + data table + graph review |
| Embedding Atlas | http://atlas.34.53.165.155.nip.io | Apple's 2D WebGPU embedding visualization |
| TensorBoard | http://tensorboard.34.53.165.155.nip.io | 3D embedding projector (PCA/t-SNE/UMAP) |
| Spotlight | http://spotlight.34.53.165.155.nip.io | Renumics dataset quality explorer |
| Neo4j Browser | http://neo4j.34.53.165.155.nip.io | Knowledge graph (Bolt: neo4j://35.233.44.47:7687) |

## Auth
All GKE services require Google OAuth (cookie shared across *.34.53.165.155.nip.io).
MCP server uses its own Google OAuth token flow at /oauth/authorize.
Local Kind services have no auth.
"""


@mcp.resource("null-realm://repos")
async def indexed_repos_resource() -> str:
    """Dynamically lists all indexed repositories with stats."""
    from nullrealm.context.repo_manager import list_indexed_repos
    repos = await list_indexed_repos()
    if not repos:
        return "No repositories indexed yet. Use the index_repo tool to add one."
    lines = ["# Indexed Repositories\n"]
    for r in repos:
        lines.append(f"## {r['repo']}")
        lines.append(f"- **Chunks**: {r['chunks']}")
        lines.append(f"- **Files**: {r['files']}")
        lines.append(f"- **First indexed**: {r.get('first_indexed', 'unknown')}\n")
    return "\n".join(lines)


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


# --- OAuth discovery + endpoints (RFC 8414 for MCP SDK) ------------------

_BASE_URL = os.getenv("MCP_BASE_URL", "http://hopocalypse.34.53.165.155.nip.io")

# In-memory store for pending auth codes (code → email mapping)
_pending_codes: dict[str, str] = {}


@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata():
    """RFC 8414 — OAuth Authorization Server Metadata.
    Claude Code's MCP SDK discovers auth endpoints from here."""
    return {
        "issuer": _BASE_URL,
        "authorization_endpoint": f"{_BASE_URL}/oauth/authorize",
        "token_endpoint": f"{_BASE_URL}/oauth/token",
        "registration_endpoint": f"{_BASE_URL}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@app.post("/oauth/register")
async def register_client(request: Request):
    """Dynamic Client Registration (RFC 7591).
    Claude Code registers itself as an OAuth client before starting the flow."""
    body = await request.json()
    # Accept any client registration — we trust the MCP SDK
    client_id = "mcp-client"
    return {
        "client_id": client_id,
        "client_name": body.get("client_name", "MCP Client"),
        "redirect_uris": body.get("redirect_uris", []),
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


@app.get("/oauth/authorize")
async def authorize(
    client_id: str = Query(None),
    redirect_uri: str = Query(None),
    state: str = Query(None),
    code_challenge: str = Query(None),
    code_challenge_method: str = Query(None),
    response_type: str = Query(None),
    scope: str = Query(None),
):
    """Start OAuth flow — redirect to Google, then back to the MCP client."""
    # Store redirect_uri and state so callback can redirect back to Claude Code
    import secrets
    session_key = secrets.token_hex(16)
    _pending_codes[session_key] = {
        "redirect_uri": redirect_uri or f"{_BASE_URL}/oauth/callback",
        "state": state or "",
        "code_challenge": code_challenge or "",
    }
    # Redirect to Google, using our own callback to intercept
    url = await get_authorize_url(state=session_key)
    return RedirectResponse(url)


@app.get("/oauth/callback")
async def callback(code: str = Query(...), state: str = Query("")):
    """Google redirects here. Exchange code, then redirect back to Claude Code with our code."""
    # Exchange Google auth code for access token
    try:
        google_tokens = await exchange_code(code)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Google token exchange failed: {exc.response.text}") from exc

    access_token = google_tokens.get("access_token")
    if not access_token:
        raise HTTPException(502, "No access_token from Google")

    email = await get_user_email(access_token)
    logger.info("OAuth callback for %s", email)

    # Generate our own auth code that Claude Code will exchange at /oauth/token
    import secrets
    our_code = secrets.token_hex(32)
    _pending_codes[our_code] = {"email": email}

    # Get the original redirect_uri from the authorize step
    session = _pending_codes.pop(state, {})
    redirect_uri = session.get("redirect_uri", f"{_BASE_URL}/oauth/callback")
    original_state = session.get("state", "")

    # Redirect back to Claude Code's redirect_uri with our code
    from urllib.parse import urlencode
    params = {"code": our_code}
    if original_state:
        params["state"] = original_state
    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}")


@app.post("/oauth/token")
async def token_exchange(request: Request):
    """Token endpoint — Claude Code exchanges our auth code for an access token."""
    # Accept both form-encoded and JSON
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    grant_type = body.get("grant_type")
    code = body.get("code")

    if grant_type != "authorization_code" or not code:
        raise HTTPException(400, detail="Invalid grant_type or missing code")

    # Look up the pending code
    pending = _pending_codes.pop(code, None)
    if not pending or "email" not in pending:
        raise HTTPException(400, detail="Invalid or expired code")

    # Issue JWT
    mcp_token = create_mcp_token(pending["email"])
    logger.info("Issued MCP token for %s via token exchange", pending["email"])
    return {
        "access_token": mcp_token,
        "token_type": "bearer",
        "expires_in": 86400,
    }


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
