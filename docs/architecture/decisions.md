# Architecture Decision Records

Decisions made during development, what worked, what didn't, and why.

---

## ADR-001: Subdomain routing over path-based routing

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Multiple services (Langfuse, Grafana, Jaeger, Chainlit) behind one Traefik ingress on GKE.

### What we tried first: path-based routing

```
34.53.165.155.nip.io/grafana/  → Grafana
34.53.165.155.nip.io/jaeger/   → Jaeger
34.53.165.155.nip.io/chat/     → Chainlit
34.53.165.155.nip.io/           → Langfuse
```

**Why it failed**:
- Grafana needed `serve_from_sub_path: true` + `root_url` config — worked but added complexity
- Jaeger v2 doesn't support `QUERY_BASE_PATH` the same way v1 did — UI loaded blank
- Chainlit has no sub-path support (Next.js/React SPA with root-relative asset paths)
- `stripPrefix` middleware stripped the path but static assets (CSS/JS) still requested from root `/`, which routed to the wrong service
- OAuth2 Proxy's multi-upstream path routing didn't work through Traefik (all requests matched `/` instead of `/grafana/`)

### What works: subdomain routing

```
34.53.165.155.nip.io            → Langfuse (via OAuth2 Proxy)
chat.34.53.165.155.nip.io       → Chainlit
grafana.34.53.165.155.nip.io    → Grafana
jaeger.34.53.165.155.nip.io     → Jaeger
api.34.53.165.155.nip.io        → FastAPI
```

**Why it works**:
- Each app thinks it's at root `/` — no sub-path configuration needed
- Static assets load correctly (relative to root)
- nip.io supports subdomains natively (`chat.34.53.165.155.nip.io` resolves to `34.53.165.155`)
- OAuth cookie set on `.34.53.165.155.nip.io` is shared across all subdomains
- Traefik uses `Host()` matching which is clean and unambiguous

**Trade-off**: Requires wildcard cookie domain (leading dot). Google OAuth redirect URI only needs the root domain.

---

## ADR-002: Direct LangGraph streaming over NATS streaming

**Date**: 2026-04-01
**Status**: Accepted (NATS ready for Phase 04)
**Context**: Stream LLM tokens from agent to Chainlit UI in real-time.

### What we tried first: NATS JetStream as message bus

```
Agent → NATS publish(text_delta) → API server subscribes → WebSocket → Chainlit
```

**Why it was problematic**:
- JetStream replays old messages on new subscriptions (same subject per session). Fixed by adding unique `msg_id` per request, but added complexity.
- Character-by-character splitting in the NATS callback (`asyncio.sleep(0.01)` per char) caused timeouts and truncated responses.
- Three layers of async (agent → NATS → WebSocket) made debugging hard — no errors logged, responses just silently truncated.
- The agent runs in-process in the API server anyway — NATS adds overhead for zero benefit at this stage.

### What works: direct streaming

```
Agent.astream_events() → WebSocket.send_text() → Chainlit.stream_token()
```

**Why it works**:
- One async loop: iterate over `astream_events(version="v2")`, send each chunk directly to WebSocket
- No middleman, no message replay issues, no character splitting needed
- LLM tokens arrive in natural chunks (words/phrases) which look smooth in the UI
- Graceful fallback: if streaming fails, returns full response via `run_agent()`

### NATS is still deployed and ready

NATS JetStream is running on Kind with the `AGENT_EVENTS` stream. The `NATSBus` client and event schemas (`TextDeltaEvent`, `ToolUseEvent`, `ToolResultEvent`, `TaskCompleteEvent`) are implemented. When Phase 04 moves agents to separate Argo pods, NATS becomes the bridge:

```
Argo pod (agent) → NATS → API server → WebSocket → Chainlit
```

The event schemas are the contract. Only the transport changes.

### Opt-in NATS connection

NATS connection is gated by the `NATS_URL` env var. If not set, the API server skips NATS entirely — no connection attempt, no error, no warning. This keeps GKE logs clean (where NATS isn't deployed) while Kind connects automatically (NATS_URL is in the deployment env vars).

```python
# main.py lifespan
if os.getenv("NATS_URL"):
    # connect to NATS
else:
    app.state.nats_bus = None  # silent skip
```

**Rule**: Infrastructure dependencies that aren't available in all environments should be opt-in via env var, not fail-and-catch. Noisy startup errors hide real problems.

---

## ADR-003: OAuth2 Proxy as reverse proxy + ForwardAuth hybrid

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Protect all GKE services with Google OAuth login.

### Architecture

```
Browser → Traefik → Service
                 ↕
          ForwardAuth checks cookie via auth-redirect nginx
                 ↕
          OAuth2 Proxy (sets/validates cookie)
```

**Two modes**:
1. **Langfuse** (root domain): OAuth2 Proxy acts as reverse proxy (`--upstream=http://langfuse:3000/`). Handles the full login flow — unauthenticated users see Google sign-in.
2. **Other services** (subdomains): Traefik ForwardAuth middleware checks the OAuth cookie. If missing, `auth-redirect` nginx converts the 401 → 302 redirect to Google login.

### Why the auth-redirect nginx wrapper

Traefik's ForwardAuth returns the upstream's response as-is. When OAuth2 Proxy's `/oauth2/auth` returns 401 (not logged in), Traefik shows "Unauthorized" text instead of redirecting to login.

The `auth-redirect` nginx sits between Traefik and OAuth2 Proxy:
- Forwards to `/oauth2/auth` (proxy_pass)
- `proxy_intercept_errors on` catches the 401
- `error_page 401 = @login_redirect` returns 302 to `/oauth2/start?rd=<original_url>`
- User gets redirected to Google login, then back to their original page

### Cookie sharing

- Cookie domain: `.34.53.165.155.nip.io` (with leading dot for subdomain sharing)
- `--prompt=select_account` forces Google to show the account picker
- Login once at root domain → cookie valid for all subdomains

---

## ADR-004: GKE Autopilot constraints

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Running on GKE Autopilot (managed node pools).

### Constraints encountered

| Constraint | Impact | Fix |
|-----------|--------|-----|
| No `hostPID`, `hostNetwork`, privileged DaemonSets | `node-exporter` can't run | Disabled in Helm values |
| All containers must have resource requests | Pods rejected without them | Set requests on everything |
| Private nodes (no public IP) | Can't pull from external registries | Added Cloud NAT to VPC |
| ARM vs AMD64 images | Mac builds ARM, GKE runs AMD64 | `docker buildx --platform linux/amd64` |
| ReadWriteOnce PVC on rolling updates | Grafana Multi-Attach errors | Changed to `Recreate` deployment strategy |

### Cloud NAT

Private GKE nodes need Cloud NAT for outbound internet access (pulling images from `registry.k8s.io`, `docker.io`, `ghcr.io`). Added via Pulumi:
```python
gcp.compute.Router("null-realm-router", ...)
gcp.compute.RouterNat("null-realm-nat", nat_ip_allocate_option="AUTO_ONLY", ...)
```

---

## ADR-005: LiteLLM probe configuration

**Date**: 2026-04-01
**Status**: Accepted
**Context**: LiteLLM pod kept crashing on Kind and GKE.

### Problem

LiteLLM's `/health` endpoint runs a full model health check (calls the LLM API). With a 1-second timeout on the liveness probe, the check consistently timed out, causing K8s to kill the pod → CrashLoopBackOff.

### Fix

- Switched to `/health/readiness` (lighter check)
- `timeoutSeconds: 10` (up from 1)
- `initialDelaySeconds: 60` for liveness (LiteLLM startup is slow)
- `failureThreshold: 5` (give it more chances)
- Memory limit: 2Gi (LiteLLM `main-latest` image is heavy, OOMKills at 512Mi/1Gi)

---

## ADR-006: Persistent WebSocket per Chainlit session

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Chat messages were replacing each other in the UI.

### Problem

The original Chainlit app opened a new WebSocket connection per message:
```python
async with websockets.connect(f"{API_URL}/{session_id}") as ws:
    # send message, receive response
```

Each new connection reset the server-side context. Previous messages disappeared from the UI.

### Fix

Open WebSocket once in `on_chat_start`, store in session, reuse for all messages:
```python
@cl.on_chat_start
async def on_chat_start():
    ws = await websockets.connect(f"{API_URL}/{session_id}")
    cl.user_session.set("ws", ws)

@cl.on_message
async def on_message(message):
    ws = cl.user_session.get("ws")
    # reuse connection
```

Auto-reconnect if the WebSocket drops between messages.

---

## ADR-007: No silent failures — structured logging at every boundary

**Date**: 2026-04-01
**Status**: Accepted
**Context**: Chat on GKE stopped responding with no errors in logs. Agent worked when tested directly inside the pod, but the Chainlit→API→LangGraph pipeline silently failed.

### Problem

The WebSocket handler caught exceptions with bare `except Exception: pass` or `except WebSocketDisconnect: pass`. When something went wrong (connection drop, streaming error, timeout), there was no log entry — just "connection open" then "connection closed".

Debugging required manual `kubectl exec` to test each component individually. With 4 services in the chain (Chainlit → API → LiteLLM → Claude), finding the broken link took too long.

### Rule

Every boundary in the pipeline must log:
1. **Entry**: what was received (message content, session ID)
2. **Exit**: what was sent (chunk count, completion status)
3. **Failure**: full exception with context (session ID, what was being attempted)

```python
# BAD — silent failure
except Exception:
    pass

# GOOD — observable failure
except Exception:
    logger.exception("Streaming failed for session %s", session_id)
```

### Applied to

- `nullrealm/api/websocket.py`: logs message received, streaming start/complete, chunk count, disconnect, every exception
- `nullrealm/communication/nats_bus.py`: logs connect/disconnect/publish failures
- `nullrealm/main.py`: logs NATS/DB init success or failure

### Future

Phase 04+ should add structured JSON logging with correlation IDs (session_id propagated through NATS → Jaeger → Langfuse) so traces can be followed across services.

---

## ADR-009: MCP server as universal agent interface with Google OAuth

**Date**: 2026-04-02
**Status**: Accepted
**Context**: Agents need access to the knowledge graph (pgvector + Neo4j). Multiple clients need access: Claude Code, Cursor, null-realm's own agents, future tools.

### Decision

Expose Graph RAG as an MCP server at `hopocalypse.34.53.165.155.nip.io/mcp` using the MCP 2025-06-18 Streamable HTTP spec. Authentication via Google OAuth token flow (not cookies).

### Why MCP over REST API

REST API works but is proprietary — every client needs custom integration. MCP is the standard protocol that Claude Code, Cursor, and other AI tools already speak. Build once, connect everywhere.

### Why token-based auth (not our existing cookie-based OAuth2 Proxy)

MCP clients are not browsers. They can't handle cookie-based auth flows. The MCP server implements its own OAuth token exchange:
1. Client connects → server returns 401
2. Client opens browser → Google login (same client ID as OAuth2 Proxy)
3. Google redirects to `/oauth/callback` with auth code
4. Server exchanges code for token, issues JWT
5. Client sends JWT as Bearer token on all requests

Same Google credentials, same consent screen, same users. Just tokens instead of cookies.

### Architecture

```
Claude Code / Any MCP client
     │  POST/GET /mcp + Bearer JWT
     ▼
hopocalypse.34.53.165.155.nip.io (Traefik, NO OAuth2 Proxy middleware)
     │
     ▼
MCP Server (FastAPI)
├─ /mcp          → Streamable HTTP (JSON-RPC + SSE)
├─ /oauth/*      → Google OAuth token exchange
├─ Tools: code_search, graph_query, graph_path, service_map
└─ Resources: repo://*/index, repo://*/graph
```

### Two modes

- **Remote (GKE)**: Streamable HTTP at `hopocalypse.34.53.165.155.nip.io/mcp`, Google OAuth
- **Local (stdio)**: `python -m nullrealm.mcp_server --stdio`, no auth (local process = trusted)

---

## ADR-008: Graph RAG over plain vector RAG for context engineering

**Date**: 2026-04-02
**Status**: Accepted
**Context**: Phase 05 originally planned pure vector RAG — embed code chunks in pgvector, search by similarity. This works for single-repo questions but fails for the actual use case: multiple microservices that call each other.

### Problem with pure vector RAG

Vector search finds code that *looks similar* to the query, but misses code that is *related* by architecture:

```
Query: "how does authentication work end-to-end?"

Vector search returns:
  ✅ auth/token.py:validate()          — has "auth" in code
  ✅ middleware/auth.py:check()         — has "auth" in code
  ❌ billing/charge.py:pre_auth_check() — called AFTER auth, but no "auth" keyword
  ❌ config/routes.yaml                 — defines which services require auth
```

The billing service depends on auth but shares no vocabulary with it. Vector similarity = 0. In a microservice architecture, the connections between services are as important as the code within them.

### Decision: Hybrid Graph RAG

Combine two retrieval strategies:

1. **pgvector (semantic similarity)**: find code chunks that match the query meaning
2. **Neo4j (graph traversal)**: starting from vector hits, walk the graph to find connected code — imports, callers, dependents, service-to-service calls

```
Vector search → starting points
     │
     ▼
Graph expansion → connected code (1-2 hops)
     │
     ▼
Merged + ranked → rich context for the agent
```

### Why Neo4j over PostgreSQL edges table

The original plan (05-02) stored the graph as a JSONB column in PostgreSQL. Neo4j was chosen because:
- Native graph traversal (vs recursive CTEs which are slow and complex)
- Built-in browser at port 7474 — interactive visualization out of the box
- Cypher query language is readable: `MATCH (a)-[:CALLS]->(b) WHERE a.name = "validate" RETURN b`
- The user's "visual first" principle: see connections, don't just trust them

### Why PaCMAP over t-SNE/UMAP for dimensionality reduction

Research (Wang et al., JMLR) shows PaCMAP preserves both global and local structure better than t-SNE (local only) or UMAP (weak global). For code embeddings, global structure matters — repos and languages should form distinct regions in the visualization, not just local function clusters.

### Why 4 visualization tools (no black boxes)

The user explicitly rejected black-box RAG: "just RAG embeddings is a black box." Each visualization serves a different purpose:

| Tool | Purpose |
|------|---------|
| **Neo4j Browser** | Explore graph: click nodes, see connections, run Cypher |
| **Apple Embedding Atlas** | 2D map: see clusters, density, hover for code snippets |
| **TensorBoard Projector** | 3D rotation: spatial understanding of embedding space |
| **Renumics Spotlight** | Data quality: filter outliers, find duplicates, audit chunks |

Plus **Chainlit retrieval transparency**: when an agent uses code_search or graph_query, show the user exactly what was retrieved, from where, with what score. No hidden context.

### Cost

- Neo4j community edition: ~$0.50/day on GKE (256Mi pod)
- Embedding viz tools: ~$0.30/day (lightweight Streamlit/static pods)
- Vertex AI embeddings: ~$0.01 per 1000 chunks indexed (one-time)
- Total Phase 05 addition: ~$1/day on top of existing ~$5.50/day

---

## ADR-010: Vertex AI embeddings via LiteLLM proxy with Workload Identity

**Date**: 2026-04-02
**Status**: Accepted
**Context**: Phase 05 needs Vertex AI `text-embedding-005` embeddings (768-dim) for code indexing. The direct approach -- calling the Vertex AI SDK from app pods -- failed because only the LiteLLM ServiceAccount has the Workload Identity binding for `aiplatform.googleapis.com`.

### What we tried first: direct Vertex AI SDK calls

```python
from google.cloud import aiplatform
model = TextEmbeddingModel.from_pretrained("text-embedding-005")
embeddings = model.get_embeddings(texts)
```

**Why it failed**:
- GKE Autopilot with Workload Identity requires each pod's K8s ServiceAccount to be bound to a GCP IAM ServiceAccount
- Only the `litellm-sa` ServiceAccount has the binding: `litellm-sa` -> `litellm@helpful-rope-230010.iam.gserviceaccount.com` -> `roles/aiplatform.user`
- Adding Workload Identity bindings to every pod that needs embeddings (indexer, MCP server, API server, worker) would mean 4+ SA bindings to maintain
- The `google-cloud-aiplatform` SDK also pulls in heavy dependencies (~200MB)

### Decision: route ALL embeddings through LiteLLM /v1/embeddings

```python
import httpx
response = httpx.post(f"{LITELLM_URL}/v1/embeddings", json={
    "model": "vertex_ai/text-embedding-005",
    "input": texts
})
embeddings = [item["embedding"] for item in response.json()["data"]]
```

**Why it works**:
- LiteLLM already runs with the correct Workload Identity SA binding -- single auth point
- No model downloads in app pods (no `sentence-transformers`, no `google-cloud-aiplatform`)
- Standard OpenAI-compatible `/v1/embeddings` API -- any client can call it
- LiteLLM handles batching, retries, and rate limiting
- Same pattern as LLM calls: all model access goes through LiteLLM proxy

### Trade-off

- LiteLLM becomes a single point of failure for embeddings (already true for LLM calls)
- Extra network hop: app pod -> LiteLLM -> Vertex AI (adds ~10ms latency, negligible for batch indexing)
- LiteLLM config must include the embedding model in its model list (forgot this initially, caused silent failures)

### Rule

Never call Vertex AI directly from application pods. Route ALL model calls (LLM + embeddings) through LiteLLM. One ServiceAccount, one proxy, one config.

---

## ADR-011: Multi-repo knowledge graph with layered cross-repo resolution

**Date**: 2026-04-03
**Status**: Accepted
**Context**: The Scality S3 platform spans 12 repositories that interact via npm dependencies, HTTP APIs, Kafka events, and shared libraries. Phase 05 indexed three repos (cloudserver, Arsenal, backbeat) but the Neo4j graph is isolated per repo -- you cannot trace a request from cloudserver's `objectPut` through Arsenal's `MetadataWrapper` to bucketd's storage layer. Single-repo graphs answer "what does this function call?" but not "what happens when a PUT object request crosses service boundaries?"

### Problem with isolated per-repo graphs

Each repo's graph is a disconnected island:

```
cloudserver graph:  objectPut --CALLS--> MetadataWrapper  (unresolved, target_file="")
Arsenal graph:      MetadataWrapper --CONTAINS--> putObjectMD
```

The CALLS edge from cloudserver to `MetadataWrapper` points to nothing because `MetadataWrapper` is defined in Arsenal, not cloudserver. There is no edge connecting the two repos. This means:

- `graph_query("objectPut", depth=3)` only returns cloudserver symbols, never reaches Arsenal
- `graph_path("objectPut", "MetadataWrapper.putObjectMD")` returns "no path found"
- `service_map()` only shows intra-repo file connections, not service-to-service topology
- The agent cannot answer "how does authentication work end-to-end?" because vault's code is in a different graph island

### Decision: Four-layer cross-repo resolution

Connect repos using four resolution layers, ordered by confidence:

1. **package.json resolution** (highest confidence): Parse npm dependencies to build a dependency map. If cloudserver depends on arsenal, create a `DEPENDS_ON` edge between their Service nodes and scope all symbol matching to known dependencies.

2. **Symbol name matching** (scoped): For unresolved CALLS targets, search dependency repos' symbols for name matches. Only search repos that are confirmed dependencies from layer 1. This prevents false positives from generic names.

3. **Federation config extraction**: Parse Ansible templates for authoritative service topology -- who talks to whom, on what ports, with what configuration. This is the ground truth for runtime communication.

4. **Code pattern detection** (lowest confidence): Detect known library usage patterns (`require('vaultclient') + new Client()`, `new BackbeatProducer()`, etc.) to create USES_CLIENT, PRODUCES, CONSUMES edges.

### Why layered resolution over a single strategy

No single strategy works for all relationship types:

- **package.json** knows library dependencies but not runtime communication
- **Code analysis** knows what code calls what but can't distinguish production code from tests or dead code
- **Federation config** knows runtime topology but not code-level symbol connections
- **Pattern detection** catches client library usage but misses indirect calls

The layers complement each other. package.json scopes the search space, code analysis finds symbol-level connections within that scope, Federation confirms runtime topology, and pattern detection fills gaps.

### Why XREF as a separate edge type (not reusing RELATES)

RELATES edges are intra-repo: both endpoints share the same `repo` property. XREF edges are cross-repo: source and target are in different repos. Keeping them separate allows:

- Filtering: `MATCH (a)-[:RELATES]-(b)` for intra-repo only, `[:XREF]` for cross-repo only
- Confidence tracking: XREF edges carry a `package` property indicating which dependency they were resolved through
- Rebuild: `link_repos()` can delete and recreate all XREF edges without touching intra-repo RELATES edges

### Why post-indexing cross-linking (not inline during index)

Cross-repo edges require both repos to be indexed. If you index cloudserver first, Arsenal's symbols don't exist yet -- you can't create XREF edges. Running `link_repos()` as a separate step after all repos are indexed means:

- Repos can be indexed in any order, independently, in parallel
- Re-indexing one repo doesn't invalidate other repos' internal graphs
- The cross-linking pass has access to all repos' symbols simultaneously
- Idempotent: `link_repos()` can be re-run safely after adding new repos

### New node types beyond Symbol

The graph expands from code-level only (Symbol) to include service-level topology:

| Node Type | Purpose |
|-----------|---------|
| Service | Deployable microservice (cloudserver, vault, bucketd, etc.) |
| Endpoint | HTTP API route a service exposes |
| Topic | Kafka topic for async communication |
| InfraService | Infrastructure dependency (redis, kafka, zookeeper) |

These connect via service-level edges (DEPENDS_ON, HTTP_CALLS, USES_CLIENT, EXPOSES, PRODUCES, CONSUMES, USES_INFRA) and link to code via BELONGS_TO (Symbol to Service).

### Trade-offs

- **Complexity**: Five node types and nine relationship types vs. the current one node type and one relationship type. More types means more code in `neo4j_store.py` and `service_analyzer.py`.
- **False positives in symbol matching**: Even scoped by package.json, common names (`get`, `put`, `create`) may match incorrectly. Mitigation: require file path context, not just symbol name.
- **Federation dependency**: Layer 3 requires access to Federation (a closed repo). Without it, the service topology is inferred from code patterns only (lower confidence).
- **Maintenance**: Adding a new repo to the ecosystem requires updating this document, re-running `link_repos()`, and verifying the topology.

### Full data model

See `docs/architecture/knowledge-graph.md` for the complete specification: all node types, relationship types, properties, example queries, and the step-by-step resolution algorithm.

---

## ADR-012: MCP Server as Query Layer, Argo as Compute Layer

**Date**: 2026-04-03

**Status**: Accepted

**Context**:
The MCP server exposes tools (index_repo, link_repos, code_search, service_topology, etc.) to Claude Code and other MCP clients. When we added cross-repo linking (link_repos) and Federation config indexing (index_federation_repo), both were initially implemented to run in-process on the MCP server pod. This failed because:

1. link_repos tried to read package.json from local filesystem clones — but clones only exist on ephemeral Argo worker pods
2. index_federation_repo tried to run git clone — but the MCP Docker image (Dockerfile.mcp) intentionally has no git installed

**Decision**:
Enforce a strict separation:

- **MCP server** = query + orchestrate (thin layer)
  - Queries pgvector (code_search, context_assemble)
  - Queries Neo4j (graph_query, graph_path, service_topology, service_deps)
  - Reads repos table (list_repos, link_repos reads dep_map from DB)
  - Submits Argo workflows (index_repo, index_federation_repo)
  - Never clones repos, never reads the filesystem, never runs parsers or embeddings

- **Argo worker pods** = clone + parse + embed + store (thick layer)
  - Clone repos (git with GITHUB_TOKEN for private repos)
  - Parse code (tree-sitter for JS/TS/Go, ast for Python)
  - Parse configs (Federation mode: text chunking)
  - Generate embeddings (Vertex AI via LiteLLM)
  - Store in pgvector + Neo4j
  - Persist dep_map to repos table for cross-repo linking
  - Create XREF edges after indexing

- **Database** = shared state
  - PostgreSQL repos table: metadata + dep_map (JSONB)
  - pgvector: code embeddings
  - Neo4j: symbol graph + service topology

All repo data that the MCP server needs is persisted in the database during Argo indexing. The MCP server never needs filesystem access to answer queries.

**Indexing modes** are controlled by a `--mode` flag on the Argo worker CLI:
- `code` (default): tree-sitter AST parsing for JS/TS/Go/Python
- `federation`: text chunking for config templates, docs, playbooks
- Future: `java`, `rust`, `docs-only` — add new modes as parsers are built

**Trade-offs**:
- (+) MCP image stays small (~200MB) — fast startup, low memory
- (+) Argo pods are ephemeral — no state accumulation, clean per-job
- (+) dep_map in DB means link_repos works without any filesystem access
- (+) --mode flag is extensible for future indexing types
- (-) Federation indexing has Argo pod startup latency (~60s on GKE Autopilot)
- (-) dep_map must be re-persisted on every re-index (minor overhead)
