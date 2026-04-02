# Architecture Overview

Null Realm is a multi-agent learning lab running on GKE Autopilot (europe-west1) with a local Kind mirror for development. Every component works in both environments.

---

## System Diagram

```
                           ┌─────────────────────────────────────────────────────────┐
                           │                    GKE Autopilot                        │
                           │                                                         │
  Browser ────────────────►│  Traefik (Ingress)                                     │
                           │    │                                                    │
                           │    ├── *.nip.io ──► OAuth2 Proxy ──► ForwardAuth       │
                           │    │                     │                               │
                           │    ├── chat.*    ──────► Chainlit (chat UI)             │
                           │    ├── api.*     ──────► FastAPI (REST + WebSocket)     │
                           │    ├── (root)    ──────► Langfuse (LLM traces)         │
                           │    ├── grafana.* ──────► Grafana (dashboards)           │
                           │    ├── jaeger.*  ──────► Jaeger (distributed traces)    │
                           │    ├── argo.*    ──────► Argo Workflows UI              │
                           │    ├── hopocalypse.* ─► MCP Server (own OAuth, no proxy)│
                           │    ├── embeddings.* ──► Embedding Explorer (Streamlit)  │
                           │    ├── atlas.*   ──────► Embedding Atlas (WebGPU)       │
                           │    ├── tensorboard.* ─► TensorBoard Projector           │
                           │    ├── spotlight.* ───► Renumics Spotlight              │
                           │    └── neo4j.*   ──────► Neo4j Browser                  │
                           │                                                         │
  Claude Code ──(MCP)────►│  MCP Server (Hopocalypse)                              │
                           │    ├── /mcp (Streamable HTTP, JSON-RPC + SSE)          │
                           │    ├── /oauth/* (Google OAuth token flow)               │
                           │    ├── code_search ──► pgvector (semantic)              │
                           │    ├── graph_query ──► Neo4j (relationships)            │
                           │    └── index_repo ──► Indexer pipeline                  │
                           │                                                         │
                           │  ┌─────────────────────────────────────────────┐        │
                           │  │ Agent Pipeline                              │        │
                           │  │                                             │        │
                           │  │ Chainlit ──ws──► FastAPI ──► LangGraph     │        │
                           │  │                               │             │        │
                           │  │                               ├──► LiteLLM ──► Claude│
                           │  │                               │             │        │
                           │  │                               └──► Tools    │        │
                           │  │                                             │        │
                           │  │ Argo Workflows ──► Worker Pods (agents)    │        │
                           │  │                      │                      │        │
                           │  │                      └──► NATS (events)     │        │
                           │  └─────────────────────────────────────────────┘        │
                           │                                                         │
                           │  ┌─────────────────────────────────────────────┐        │
                           │  │ Data Stores                                 │        │
                           │  │                                             │        │
                           │  │ Cloud SQL (PostgreSQL 16 + pgvector)        │        │
                           │  │   ├── App data (registry, sessions)         │        │
                           │  │   ├── Langfuse traces                       │        │
                           │  │   └── code_embeddings (768-dim vectors)     │        │
                           │  │                                             │        │
                           │  │ Neo4j 5 Community                           │        │
                           │  │   └── Symbol nodes + relationship edges     │        │
                           │  │                                             │        │
                           │  │ NATS JetStream (AGENT_EVENTS stream)        │        │
                           │  │   └── TextDelta, ToolUse, TaskComplete      │        │
                           │  └─────────────────────────────────────────────┘        │
                           └─────────────────────────────────────────────────────────┘
```

---

## Component Layers

### 1. Ingress

**Traefik** with `Host()` subdomain matching. All subdomains resolve via nip.io (`*.34.53.165.155.nip.io` -> `34.53.165.155`).

- Cookie-based auth: OAuth2 Proxy + ForwardAuth middleware (browser traffic)
- Token-based auth: MCP server handles its own Google OAuth (AI tool traffic)
- Cookie domain: `.34.53.165.155.nip.io` (shared across all subdomains)

See ADR-001 (subdomain routing) and ADR-003 (OAuth2 Proxy) in `decisions.md`.

### 2. UI Layer

| Component | Tech | Purpose |
|-----------|------|---------|
| Chainlit | Next.js/React SPA | Chat interface with streaming, tool step visualization, chain-of-thought |
| Grafana | `11.2.2` | K8s metrics, Argo workflow dashboards, (planned) cost + model comparison |
| Neo4j Browser | Built into Neo4j | Interactive Cypher queries, visual graph exploration |
| Embedding Explorer | Streamlit + Plotly | 2D/3D scatter plots, data table, graph review |
| Embedding Atlas | Apple WebGPU | High-performance 2D embedding map |
| TensorBoard | Projector plugin | 3D embedding viewer with PCA/t-SNE/UMAP |
| Spotlight | Renumics | Dataset quality: filter outliers, find duplicates, audit chunks |

### 3. API Layer

**FastAPI** server (`nullrealm/main.py`) providing:
- REST endpoints: `/health`, `/api/v1/registry/*` (CRUD for tools, prompts, assistants, workflows), `/api/v1/workflows/*`
- WebSocket: persistent connection per Chainlit session for real-time streaming
- Agent invocation: receives messages, runs LangGraph agent, streams response tokens back

### 4. Agent Layer

**LangGraph** ReAct agents with tool calling:
- Agent receives a task + assembled context
- Calls tools (code_search, graph_query, file_read, bash) via LangGraph tool nodes
- Streams events via `astream_events(version="v2")` directly to WebSocket

**Argo Workflows** for multi-step orchestration:
- WorkflowTemplate defines agent pipeline steps (research -> plan -> implement -> review)
- Each step runs in a separate worker pod
- NATS JetStream bridges pod-to-API streaming (Kind; GKE uses direct streaming)

### 5. AI Layer

**LiteLLM** proxy as the single gateway for all model calls:
- LLM: Claude (Anthropic) via API key
- Embeddings: Vertex AI `text-embedding-005` (768-dim) via Workload Identity SA
- Standard OpenAI-compatible API (`/v1/chat/completions`, `/v1/embeddings`)
- Handles auth (Workload Identity), retries, rate limiting

See ADR-010 (Vertex AI embeddings via LiteLLM) in `decisions.md`.

### 6. Data Layer

| Store | Technology | Contents |
|-------|-----------|----------|
| **PostgreSQL** | Cloud SQL PostgreSQL 16 (GKE), pgvector container (Kind) | App registry (tools, prompts, assistants, workflows), Langfuse traces, code embeddings |
| **pgvector** | Extension on PostgreSQL | `code_embeddings` table: 768-dim vectors, cosine similarity search |
| **Neo4j** | Neo4j 5 Community | `Symbol` nodes with properties (name, file, type). Edges: `:IMPORTS`, `:CALLS`, `:EXTENDS` |
| **NATS JetStream** | `AGENT_EVENTS` stream | Event schemas: `TextDeltaEvent`, `ToolUseEvent`, `ToolResultEvent`, `TaskCompleteEvent` |

### 7. Observability Layer

| System | What it captures | How |
|--------|-----------------|-----|
| **Langfuse** | LLM traces: tokens, cost, latency per call | LiteLLM `success_callback: ["langfuse"]` |
| **Jaeger** | Distributed traces: spans across services | OpenTelemetry SDK + OTLP exporter |
| **Prometheus + Grafana** | K8s pod metrics, Argo workflow metrics | ServiceMonitor + scrape configs |

---

## Key Data Flows

### Chat message -> agent response

```
Chainlit (browser)
  │  WebSocket.send({"message": "..."})
  ▼
FastAPI WebSocket handler (nullrealm/api/websocket.py)
  │  Parse message, load session
  ▼
LangGraph agent (nullrealm/worker/langgraph_agent.py)
  │  agent.astream_events(version="v2")
  │    ├── on_chat_model_stream -> stream token to WebSocket
  │    ├── on_tool_start -> log tool call
  │    └── on_tool_end -> log tool result
  ▼
LiteLLM proxy
  │  POST /v1/chat/completions (streaming)
  ▼
Claude (Anthropic API)
```

### Code indexing pipeline

```
index_repo(url, branch)
  │
  ├── 1. git clone --depth 1 (or git pull if cached)
  │
  ├── 2. AST parse all .py files
  │      ├── Extract: functions, classes, module-level code
  │      └── Extract: imports, calls, inheritance (CodeRelationship)
  │
  ├── 3. Embed each CodeChunk
  │      └── POST LiteLLM /v1/embeddings (vertex_ai/text-embedding-005)
  │          └── 768-dim vector per chunk
  │
  ├── 4. Store in pgvector
  │      └── INSERT INTO code_embeddings (repo, file_path, symbol_name, embedding, ...)
  │
  ├── 5. Store in Neo4j
  │      └── MERGE (Symbol) nodes + CREATE relationship edges
  │
  └── 6. Generate REPO_INDEX.md summary
         └── Saved to repo-indexes/<repo_name>/REPO_INDEX.md
```

### MCP tool call (remote)

```
Claude Code (or any MCP client)
  │  POST /mcp + Bearer JWT
  │  JSON-RPC: {"method": "tools/call", "params": {"name": "code_search", "arguments": {...}}}
  ▼
MCP Server (Hopocalypse)
  │  Verify JWT, dispatch to tool handler
  ▼
do_code_search(query, repo, k)
  │  Embed query via LiteLLM
  │  SELECT ... ORDER BY embedding <=> query_embedding LIMIT k
  ▼
pgvector (PostgreSQL)
  │  Return ranked code chunks
  ▼
MCP Server
  │  JSON-RPC response with formatted results
  ▼
Claude Code
```

### Hybrid Graph RAG (context_assemble)

```
context_assemble(query)
  │
  ├── 1. Load REPO_INDEX.md (high-level architecture summary)
  │
  ├── 2. Vector search (pgvector)
  │      └── Top 5 semantically similar code chunks
  │
  └── 3. Graph expansion (Neo4j)
         └── For top 3 vector hits, find neighbors at depth=1
         └── Merge and deduplicate
  │
  ▼
AssembledContext
  ├── repo_summary (truncated to 2000 chars)
  ├── vector_results (top 5 with scores)
  ├── graph_paths (up to 10 related symbols)
  └── total_tokens (estimated)
```

---

## Infrastructure

| Aspect | Detail |
|--------|--------|
| **Cloud** | GCP project `helpful-rope-230010`, region `europe-west1` |
| **Cluster** | GKE Autopilot (managed nodes, pay-per-pod) |
| **Database** | Cloud SQL PostgreSQL 16 (`null-realm-db`) with pgvector extension |
| **Networking** | VPC `null-realm-vpc` + private nodes + Cloud NAT for outbound |
| **IaC** | Pulumi Python (local state, `infra/pulumi/`) |
| **Images** | Artifact Registry `europe-west1-docker.pkg.dev/helpful-rope-230010/null-realm/` |
| **Secrets** | GCP Secret Manager + K8s Secrets (`llm-api-keys`, `oauth2-proxy-secrets`) |
| **Local dev** | Kind cluster (`kind-null-realm` context), images loaded via `kind load` |
| **DNS** | nip.io wildcard DNS (no custom domain) |
| **Deployment** | Manual `docker buildx --platform linux/amd64 --push` + `kubectl apply` |

### GKE Autopilot Constraints

See ADR-004 in `decisions.md` for details. Key constraints:
- No privileged DaemonSets (no node-exporter)
- All containers need resource requests
- Private nodes require Cloud NAT
- ARM vs AMD64: always build `--platform linux/amd64`
- ReadWriteOnce PVC: use `Recreate` deployment strategy (not `RollingUpdate`)

---

## Project Phases

| Phase | Status | Key Deliverables |
|-------|--------|-----------------|
| 01: Foundation + Observability | Complete | Kind + GKE + Grafana + Jaeger + Langfuse |
| 02: Chat UI + First Agent | Complete | Chainlit + FastAPI + LiteLLM + LangGraph |
| 03: Streaming + Persistence | Complete | NATS JetStream + PostgreSQL + Registry API |
| 04: Multi-Agent Workflows | Complete | Argo Workflows + multiple assistants |
| 05: Context Engineering | Complete | Repo indexing + pgvector + Neo4j + MCP server + 4 viz tools |
| 06: Model Comparison + Eval | Not started | Multi-model comparison + LLM judge + golden tests |

See `.planning/ROADMAP.md` for full phase details.
