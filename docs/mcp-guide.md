# Hopocalypse MCP Server Guide

Hopocalypse is null-realm's MCP (Model Context Protocol) server. It gives AI tools access to the code knowledge graph -- semantic search, relationship traversal, repo indexing, and service discovery.

Server name: `null-realm`, protocol version: `2025-11-25`, SDK: `mcp>=1.26.0`.

---

## Connecting

### Remote (GKE) -- Streamable HTTP

```bash
claude mcp add --transport http hopocalypse http://hopocalypse.34.53.165.155.nip.io/mcp
```

First use: Claude Code opens a browser tab for Google OAuth login. After consent, the server issues a JWT. All subsequent requests use `Bearer <jwt>` automatically.

### Local (stdio)

Add to your Claude Code MCP settings (`.claude/settings.json` or project-level `.mcp.json`):

```json
{
  "mcpServers": {
    "null-realm-local": {
      "command": "uv",
      "args": ["run", "python", "-m", "nullrealm.mcp_server", "--stdio"],
      "cwd": "/Users/anurag4dsb/anurag-builds-things/agents/building-null-realm/null-realm",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:15432/nullrealm",
        "NEO4J_URI": "bolt://localhost:7687"
      }
    }
  }
}
```

**Prerequisites** -- port-forward from the Kind cluster before using:

```bash
kubectl port-forward svc/postgres -n null-realm 15432:5432 --context kind-null-realm &
kubectl port-forward svc/neo4j -n null-realm 7687:7687 --context kind-null-realm &
```

No authentication in stdio mode (local process = trusted).

See also: `docs/mcp-local-config.md` for the standalone reference.

---

## Available Tools (8)

### Code Intelligence (5 tools)

| Tool | Parameters | What it does |
|------|-----------|--------------|
| `code_search` | `query` (str), `repo` (str, default `"null-realm"`), `k` (int, default `10`) | Embed query via Vertex AI, return top-k similar code chunks from pgvector (cosine similarity) |
| `graph_query` | `symbol` (str), `depth` (int, default `2`) | Find all symbols connected to `symbol` within `depth` hops in Neo4j |
| `graph_path` | `source` (str), `target` (str) | Shortest path (up to 5 hops) between two symbols in the Neo4j graph |
| `service_map` | *(none)* | All file-to-file connections extracted from AST analysis |
| `context_assemble` | `query` (str) | Full hybrid Graph RAG: REPO_INDEX.md + vector search + graph expansion. Use this for comprehensive context. |

### Repository Management (3 tools)

| Tool | Parameters | What it does |
|------|-----------|--------------|
| `index_repo` | `url` (str), `branch` (str, default `"main"`), `name` (str, optional) | Clone a Git repo + run full indexing pipeline (AST parse, embed, graph). Supports SSH and HTTPS. Idempotent. |
| `delete_repo_index` | `repo_name` (str) | Remove all data for a repo: pgvector chunks, Neo4j nodes, REPO_INDEX.md, cached clone |
| `list_repos` | *(none)* | Show all indexed repos with chunk count, file count, and first-indexed date |

---

## Example Usage

### Semantic code search

```
Use the code_search tool to find how authentication works in null-realm.
```

Returns scored results with file paths and code snippets:

```
[0.847] nullrealm/mcp_auth.py:verify_mcp_token (function)
```python
def verify_mcp_token(token: str) -> dict:
    ...
```
```

### Graph traversal

```
Use graph_query to find everything connected to the symbol "PgVectorStore" with depth 2.
```

Returns neighbors with distance and type:

```
Neighbors of 'PgVectorStore' (depth=2):
  [1] nullrealm/context/pgvector_store.py:search (function)
  [1] nullrealm/context/pgvector_store.py:init (function)
  [2] nullrealm/mcp_tools.py:do_code_search (function)
```

### Finding the path between two symbols

```
Use graph_path to find the connection from "ContextAssembler" to "Neo4jStore".
```

### Full context assembly

```
Use context_assemble to understand how the indexing pipeline works end-to-end.
```

Returns structured context with three sections:
1. **Repository Overview** -- from REPO_INDEX.md
2. **Relevant Code** -- top 5 vector search hits with scores
3. **Related Code** -- graph-connected symbols from top 3 hits

### Index a new repository

```
Use index_repo to index https://github.com/org/repo.git on the main branch.
```

For private repos, use SSH URL: `git@github.com:org/repo.git`

### Check what is indexed

```
Use list_repos to see all indexed repositories.
```

---

## Available Resources (3)

| Resource | URI | What it returns |
|----------|-----|-----------------|
| **REPO_INDEX** | `repo://null-realm/index` | REPO_INDEX.md -- architecture summary of null-realm |
| **Services** | `null-realm://services` | All deployed service URLs, organized by category |
| **Repos** | `null-realm://repos` | Dynamic list of indexed repos with chunk/file counts |

---

## Authentication

| Mode | Auth | Details |
|------|------|---------|
| **Remote (GKE)** | Google OAuth token flow | RFC 8414 discovery at `/.well-known/oauth-authorization-server`. Client registers via RFC 7591, then standard auth code flow with PKCE (S256). Server issues JWT (24h expiry). |
| **Local (stdio)** | None | Trusted local process, no auth needed |

### OAuth endpoints (remote only)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/.well-known/oauth-authorization-server` | GET | RFC 8414 metadata discovery |
| `/oauth/register` | POST | Dynamic client registration (RFC 7591) |
| `/oauth/authorize` | GET | Start OAuth flow (redirects to Google) |
| `/oauth/callback` | GET | Google redirects here after consent |
| `/oauth/token` | POST | Exchange auth code for JWT |
| `/oauth/verify` | GET | Verify a JWT (debug endpoint) |

OAuth callback URL: `http://hopocalypse.34.53.165.155.nip.io/oauth/callback`

The MCP server does NOT go through OAuth2 Proxy -- it handles its own Google OAuth with token-based auth (same Google client ID, same users, but tokens instead of cookies). See ADR-009 in `docs/architecture/decisions.md`.

---

## Indexing a New Repository

### Via MCP tool (recommended)

1. Connect to the MCP server (remote or local)
2. Call `index_repo` with the repo URL:
   ```
   Use index_repo to index https://github.com/org/repo.git
   ```
3. The tool will:
   - Clone the repo (shallow, `--depth 1`)
   - Parse all Python files via AST
   - Extract symbols (functions, classes, modules) and relationships (imports, calls, extends)
   - Embed each code chunk via Vertex AI `text-embedding-005` (768-dim) through LiteLLM
   - Store embeddings in pgvector
   - Store relationships in Neo4j
   - Generate a REPO_INDEX.md summary
4. Verify with `list_repos`

### Via CLI (direct)

```bash
cd /Users/anurag4dsb/anurag-builds-things/agents/building-null-realm/null-realm
uv run python -m nullrealm.context.indexer /path/to/repo --embed --graph
```

### Re-indexing

Re-indexing is idempotent -- calling `index_repo` on an already-indexed repo replaces old data. For a clean slate, call `delete_repo_index` first.

### What gets indexed

- **Parsed**: all `.py` files (AST-based extraction of functions, classes, module-level code)
- **Skipped**: `.git`, `__pycache__`, `.venv`, `venv`, `node_modules`, `.mypy_cache`, `.ruff_cache`, `.tox`, `site-packages`
- **Relationships extracted**: imports, function calls, class inheritance, attribute access
- **Stored in pgvector**: one row per code chunk with 768-dim embedding vector
- **Stored in Neo4j**: `Symbol` nodes with `:IMPORTS`, `:CALLS`, `:EXTENDS` edges

---

## How `index_repo` Works (Step by Step)

```
You say: "use index_repo to index https://github.com/scality/service-a.git"

Step 1: CLONE
   git clone --depth 1 --branch main <url> /tmp/null-realm-repos/service-a/
   (shallow clone — only latest commit, fast)
   If already cloned → git pull instead

Step 2: AST PARSE
   Walk all .py files in the clone
   Python ast module extracts:
   ├─ Functions → CodeChunk (name, code text, line numbers)
   ├─ Classes → CodeChunk
   ├─ Modules → CodeChunk
   └─ Relationships → IMPORTS, CALLS, INHERITS, CONTAINS

Step 3: EMBED
   Send all chunk texts to LiteLLM → Vertex AI text-embedding-005
   Each chunk → 768-dim vector
   Batch processing (250 texts per batch)

Step 4: STORE EMBEDDINGS (pgvector)
   DELETE FROM code_embeddings WHERE repo = 'service-a'  ← clear old data
   INSERT rows with (text, vector, file_path, symbol_name, ...)
   HNSW index auto-updates for fast search

Step 5: STORE GRAPH (Neo4j)
   For each relationship:
   MERGE (a:Symbol) -[:RELATES {type}]-> (b:Symbol)
   Neo4j MERGE = idempotent (safe to re-run)

Step 6: GENERATE SUMMARY
   Send file tree + AST signatures to Claude via LiteLLM
   Claude writes REPO_INDEX.md → saved to repo-indexes/service-a/

Step 7: RETURN
   "Indexed 'service-a': 247 chunks, 892 relationships"
```

### Is data immediately available?

**Yes — the moment indexing finishes, everything is live:**

- `code_search("auth handler")` → finds service-a code immediately
- `graph_query("validate_token")` → finds service-a connections immediately
- `context_assemble("how does auth work")` → includes service-a in results
- `list_repos()` → shows service-a with stats

No restart needed. No cache to invalidate. No rebuild. The data is in PostgreSQL and Neo4j — every query hits the live database.

**Re-indexing** is also immediate: calling `index_repo` again deletes old data first, then inserts fresh. No stale results.

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `code_search` returns no results | Repo not indexed, or pgvector not reachable | Run `list_repos` to check; verify `DATABASE_URL` env var |
| `graph_query` returns no neighbors | Neo4j not running or no graph data | Check `NEO4J_URI` env var; verify Neo4j pod is up |
| OAuth flow opens but never completes | MCP client redirect URI mismatch | Check Claude Code version supports MCP OAuth |
| `index_repo` fails on private repo | SSH key not available in the pod | Use SSH URL (`git@github.com:...`) and ensure SSH key is mounted |
| Embeddings fail silently | LiteLLM missing `vertex_ai/text-embedding-005` in model list | Check LiteLLM config includes the embedding model |
