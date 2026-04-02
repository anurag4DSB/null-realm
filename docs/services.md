# Null Realm -- Service Catalog

Quick reference for every deployed service, URL, and technology.

---

## Service URLs

### GKE (Production)

All GKE services require **Google OAuth** (cookie shared across `*.INGRESS_IP.nip.io`).

| Service | URL | Purpose |
|---------|-----|---------|
| **Chat (Chainlit)** | http://chat.INGRESS_IP.nip.io | Chat with Claude via LangGraph agent |
| **MCP Server (Hopocalypse)** | http://hopocalypse.INGRESS_IP.nip.io/mcp | MCP tools: code search, graph query, repo indexing |
| **API Server** | http://api.INGRESS_IP.nip.io | REST API + WebSocket (`/health`, `/api/v1/registry/*`, `/api/v1/workflows/*`) |
| **Langfuse** | http://INGRESS_IP.nip.io | LLM traces (tokens, cost, latency) |
| **Grafana** | http://grafana.INGRESS_IP.nip.io | Dashboards: K8s, Argo Workflows, Code Knowledge Graph |
| **Jaeger** | http://jaeger.INGRESS_IP.nip.io | Distributed traces (OpenTelemetry spans) |
| **Argo Workflows** | http://argo.INGRESS_IP.nip.io | Multi-agent workflow orchestration UI |
| **Embedding Explorer** | http://embeddings.INGRESS_IP.nip.io | 2D/3D scatter + data table + graph review |
| **Embedding Atlas** | http://atlas.INGRESS_IP.nip.io | Apple WebGPU 2D embedding map |
| **TensorBoard** | http://tensorboard.INGRESS_IP.nip.io | 3D embedding projector (PCA/t-SNE/UMAP) |
| **Spotlight** | http://spotlight.INGRESS_IP.nip.io | Renumics dataset quality explorer |
| **Neo4j Browser** | http://neo4j.INGRESS_IP.nip.io | Knowledge graph browser + Cypher console |

**Neo4j Bolt endpoint** (for connecting Neo4j Browser to the server): `neo4j://NEO4J_EXTERNAL_IP:7687`

### Local (Kind)

No authentication required.

| Service | URL | Credentials |
|---------|-----|-------------|
| Chat (Chainlit) | http://localhost:8501 | -- |
| API Server | http://localhost:8000 | -- |
| Grafana | http://localhost:3000 | admin / admin |
| Jaeger | http://localhost:16686 | -- |
| Langfuse | http://localhost:3001 | account you create on first visit |
| Argo Workflows | http://localhost:2746 | -- |
| Others | via `kubectl port-forward` | -- |

---

## Tech Stack

| Component | Technology | Version / Image | Purpose |
|-----------|-----------|-----------------|---------|
| **Chat UI** | Chainlit | `>=2.0.0` | Conversational interface with streaming + tool steps |
| **API Server** | FastAPI + Uvicorn | `>=0.115.0` / `>=0.30.0` | REST API, WebSocket, agent orchestration |
| **Agent Framework** | LangGraph | `>=0.4.0` | ReAct agents with tool calling |
| **LLM Proxy** | LiteLLM | `ghcr.io/berriai/litellm:main-latest` | Unified API for Claude + Vertex AI embeddings |
| **LLM** | Claude (Anthropic) | via LiteLLM | Primary model for all agent tasks |
| **Embeddings** | Vertex AI `text-embedding-005` | 768-dim, via LiteLLM `/v1/embeddings` | Code chunk embeddings for semantic search |
| **MCP Server** | FastMCP (Python `mcp` SDK) | `>=1.26.0` | Streamable HTTP + stdio transport for code intelligence tools |
| **Vector Store** | PostgreSQL 16 + pgvector | `pgvector/pgvector:pg16` | Semantic code search (cosine similarity) |
| **Graph DB** | Neo4j Community | `neo4j:5-community` | Code relationship graph (imports, calls, extends) |
| **Message Bus** | NATS JetStream | `nats:2.10-alpine` | Agent-to-UI streaming (Kind only, opt-in via `NATS_URL`) |
| **Workflow Engine** | Argo Workflows | Helm chart (v4) | Multi-agent workflow orchestration |
| **Ingress** | Traefik | Helm chart | Subdomain routing + ForwardAuth |
| **Auth (GKE)** | OAuth2 Proxy | `v7.7.1` | Google OAuth login, cookie shared across subdomains |
| **Auth (MCP)** | Custom Google OAuth | JWT (PyJWT `>=2.12.1`) | Token-based auth for MCP clients |
| **LLM Traces** | Langfuse | `langfuse/langfuse:2` | Token usage, cost, latency per LLM call |
| **Distributed Traces** | Jaeger | `jaegertracing/jaeger:2.17.0` | OpenTelemetry spans across services |
| **Metrics** | Prometheus + Grafana | Prom `v2.54.1`, Grafana `11.2.2` | K8s metrics, dashboards |
| **OTEL SDK** | OpenTelemetry Python | `>=1.29.0` | Instrumentation + OTLP export |
| **Dim. Reduction** | PaCMAP | `>=0.9.1` | 2D/3D projection of embedding space |
| **Viz (Explorer)** | Streamlit + Plotly | `>=1.56.0` / `>=6.6.0` | Interactive embedding scatter plots |
| **Viz (Atlas)** | Apple Embedding Atlas | custom image | WebGPU 2D embedding map |
| **Viz (Spotlight)** | Renumics Spotlight | custom image | Dataset quality + outlier detection |
| **Viz (TensorBoard)** | TensorBoard Projector | custom image | 3D PCA/t-SNE/UMAP embedding viewer |
| **IaC** | Pulumi (Python) | local state | GKE, Cloud SQL, VPC, IAM, Secret Manager |
| **Local K8s** | Kind | -- | Local development cluster |
| **Task Runner** | Invoke | `>=2.2.0` | `tasks.py` for build/deploy/manage commands |
| **Package Manager** | uv | -- | Fast Python dependency management |
| **Registry** | GCP Artifact Registry | `europe-west1-docker.pkg.dev/YOUR_GCP_PROJECT/null-realm/` | Docker images for GKE |
| **Database (GKE)** | Cloud SQL PostgreSQL 16 | `null-realm-db` | Shared DB for app + Langfuse + pgvector |

---

## GCP Resources

All in `europe-west1`, project `YOUR_GCP_PROJECT`.

| Resource | Name | Purpose |
|----------|------|---------|
| GKE Autopilot | `null-realm` | All workloads |
| Cloud SQL PostgreSQL 16 | `null-realm-db` | App + Langfuse + pgvector |
| Artifact Registry | `null-realm` | Docker images |
| Secret Manager | `ANTHROPIC_API_KEY`, `DATABASE_URL`, `OAUTH2_*` | Secrets |
| VPC + Subnet | `null-realm-vpc` | Private networking |
| Cloud NAT | `null-realm-nat` | Outbound internet for private nodes |

---

## Cost

| Scenario | $/day | $/month |
|----------|-------|---------|
| Full stack (all pods) | ~$7.70 | ~$231 |
| Observability only | ~$5.50 | ~$165 |
| Cluster on, no pods | ~$4.20 | ~$126 |
| Everything stopped (storage only) | ~$0.58 | ~$17 |
| Destroyed (`pulumi destroy`) | $0 | $0 |

See `.planning/COSTS.md` for full breakdown. Cost control commands are in `RUNBOOK.md`.
