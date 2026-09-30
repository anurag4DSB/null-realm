# Null Realm

Null Realm is a lab to build, deploy, and evaluate multi-agent systems on Kubernetes. It runs on GKE Autopilot in `europe-west1`, with a local Kind cluster for development. Each component works in both environments.

The lab has three parts:

- An agent pipeline. You chat with an agent in Chainlit. FastAPI sends the request to a LangGraph agent, which calls models through LiteLLM. Argo Workflows runs multi-step workflows across worker pods, and NATS carries the events between them.
- A code knowledge graph. The indexer parses repositories with tree-sitter. It stores code embeddings (vectors that represent the meaning of code) in pgvector and code relationships in Neo4j.
- An MCP server named Hopocalypse. MCP (Model Context Protocol) lets AI tools such as Claude Code call external tools. Hopocalypse gives these tools code search, graph queries, and repository indexing.

Langfuse, Jaeger, Prometheus, and Grafana trace and measure each request, model call, and tool call.

## Status and access

The live deployment is internal only. The public demo URLs are not available.

You cannot run this project from this repository alone. It needs these private resources:

- A GCP project with GKE Autopilot, Cloud SQL, Artifact Registry, and Secret Manager.
- A Google OAuth client and a list of allowed emails.
- API keys for Anthropic and Google Gemini.
- The Kubernetes secrets that the manifests in `infra/k8s/` refer to.
- An indexed knowledge graph in pgvector and Neo4j.

The repository uses placeholders such as `YOUR_GCP_PROJECT` and `INGRESS_IP` in place of the real values. The commit history was rewritten to remove internal configuration and infrastructure details. The commits and their messages stay the same.

For access or a demo, contact the repository owner, [@anurag4DSB](https://github.com/anurag4DSB).

## Stack

| Area | Tools |
|------|-------|
| Agents | LangGraph, LiteLLM, Claude, Gemini |
| API and UI | FastAPI, Chainlit, Streamlit |
| Orchestration | Argo Workflows, NATS JetStream |
| Data | PostgreSQL 16 with pgvector, Neo4j 5 |
| Observability | Langfuse, OpenTelemetry, Jaeger, Prometheus, Grafana |
| Infrastructure | GKE Autopilot, Kind, Pulumi (Python), Cloud Build |

## Repository layout

| Path | Contents |
|------|----------|
| `nullrealm/` | Python package: API, worker, orchestrator, registry, tools, and the context indexer |
| `nullrealm/mcp_server.py` | The Hopocalypse MCP server |
| `agent_configs/` | Assistant, prompt, tool, and workflow definitions |
| `ui/` | Chainlit chat UI |
| `viz/` | Embedding and knowledge graph visualization apps |
| `infra/` | Kubernetes manifests, Prometheus configuration, and Pulumi code |
| `docs/` | Architecture, decisions, service catalog, and MCP guides |
| `.planning/` | Project brief, roadmap, phase plans, and costs |
| `tasks.py` | `invoke` tasks for build, deploy, and cloud operations |

## Local development

These steps are for the owner and need the private resources in [Status and access](#status-and-access). You need Python 3.12 or later and [uv](https://docs.astral.sh/uv/). For the Kind path, you also need Docker, `kind`, `kubectl`, and `helm`.

1. Install the dependencies:

   ```bash
   uv sync
   ```

2. Copy the environment file, then add your API keys:

   ```bash
   cp .env.example .env
   ```

3. Start the infrastructure services (PostgreSQL, NATS, Jaeger, Langfuse, Prometheus, Grafana):

   ```bash
   docker compose up -d
   ```

4. Start the API:

   ```bash
   uv run uvicorn nullrealm.main:app --reload
   ```

To run the full stack on a local Kind cluster instead, use this command:

```bash
uv run invoke dev
```

This command creates the cluster, builds and loads the images, and applies the manifests.

## Documentation

- [RUNBOOK.md](RUNBOOK.md): day-to-day commands for local and GCP work, including cost control.
- [docs/architecture/overview.md](docs/architecture/overview.md): the system diagram and component details.
- [docs/architecture/decisions.md](docs/architecture/decisions.md): architecture decision records.
- [docs/services.md](docs/services.md): the service catalog with URLs.
- [docs/mcp-guide.md](docs/mcp-guide.md): how to connect to and use the Hopocalypse MCP server.
- [docs/architecture/knowledge-graph.md](docs/architecture/knowledge-graph.md): the state of the code knowledge graph.

## License

Apache License 2.0. See [LICENSE](LICENSE).
