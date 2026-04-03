# Roadmap: Null Realm

## Overview

Build a multi-agent learning lab on GKE, starting with visual infrastructure (dashboards, tracing, chat UI) and layering in agents, orchestration, context engineering, and model comparison. Every step works locally on Kind and auto-deploys to GKE on push to main.

## Key Decisions (Made)

- **IaC**: Pulumi Python (not Terraform) — real Python code for GCP infrastructure. Pulumi manages GCP resources (GKE, Cloud SQL, networking, IAM, Secret Manager). Helm manages K8s workloads.
- **Local K8s**: Kind cluster, always available alongside GKE
- **LLM Access**: API keys via `.env` locally, Secret Manager on GKE. Start with Claude (Anthropic API key), add Gemini later for comparison
- **Visual First**: Observability deployed before application code. UI before backend when possible
- **GCP Project**: `helpful-rope-230010` (europe-west1 region)
- **Task Runner**: Invoke (tasks.py) — Python-native, not Makefile
- **Auth**: OAuth2 Proxy + Traefik on GKE (Phase 01-03). Google OAuth login. No auth on local Kind. Upgrade path: Pomerium.

## Open Decisions (Resolve During Execution)

1. **Web search tool** (Phase 02): Tavily API vs SerpAPI vs stub — decide in 02-02
2. ~~**Traefik timing**~~ → DECIDED: Phase 01-03 with OAuth2 Proxy
3. **KEDA timing** (Phase 04 or later): Deploy autoscaler with Argo or defer until post-v1.0
4. ~~**Anthropic API key**~~ → DECIDED: Claude as primary LLM from Phase 02. Add Gemini in Phase 06 for comparison.

## Deployment Architecture

```
LOCAL (Kind cluster)                    GKE (Autopilot)
┌──────────────────────┐               ┌──────────────────────┐
│ invoke kind-up       │               │ pulumi up            │
│ invoke deploy-local  │──push main──→ │ Cloud Build triggers │
│ invoke test-local    │               │ → build images       │
│                      │               │ → push to AR         │
│ localhost:8000 (API) │               │ → kubectl apply      │
│ localhost:8501 (UI)  │               │                      │
│ localhost:3000 (Graf)│               │ External IPs via     │
│ localhost:16686 (Jae)│               │ Traefik Ingress      │
│ localhost:3001 (Lang)│               │                      │
│ localhost:2746 (Argo)│               │                      │
└──────────────────────┘               └──────────────────────┘
```

**Credentials**: `.env` locally (gitignored), Secret Manager on GKE. `.env.example` documents every var + where to get each key.

## E2E Verification (After Phase 04)

1. Chainlit → trigger "feature-development" workflow
2. Argo spawns 4 pods: research → plan → implement → review
3. Each step streams to Chainlit in real-time via NATS
4. Langfuse shows full workflow trace with per-step spans
5. Grafana shows pod metrics and costs

## Phases

- [ ] **Phase 01: Foundation + Observability** — Local Kind + GKE + CI/CD + dashboards (Grafana, Jaeger, Langfuse)
- [ ] **Phase 02: Chat UI + First Agent** — Chainlit + FastAPI + LiteLLM + LangGraph agent with tracing
- [ ] **Phase 03: Streaming + Persistence** — NATS real-time streaming + PostgreSQL + registry CRUD API
- [ ] **Phase 04: Multi-Agent Workflows** — Argo Workflows + multiple assistants + step visualization
- [ ] **Phase 05: Context Engineering** — Repo indexing + pgvector RAG + context assembly
- [ ] **Phase 06: Model Comparison + Eval** — Multi-model comparison + LLM judge + golden tests + dashboards

## Phase Details

### Phase 01: Foundation + Observability
**Goal**: See dashboards running on local Kind AND GKE. CI/CD pipeline auto-deploys on push.
**Depends on**: Nothing (first phase)
**Plans**: 3 plans

Plans:
- [x] 01-01: Project scaffold + local Kind cluster setup
- [x] 01-02: Observability stack — Prometheus/Grafana, Jaeger, Langfuse on Kind
- [x] 01-03: GKE Autopilot via Pulumi + Cloud Build CI/CD + observability on GKE

### Phase 02: Chat UI + First Agent
**Goal**: Type a message in Chainlit, get a response from a LangGraph agent, see traces in Langfuse/Jaeger.
**Depends on**: Phase 01
**Plans**: 2 plans

Plans:
- [x] 02-01: Chainlit chat UI + FastAPI skeleton with WebSocket
- [x] 02-02: LiteLLM proxy + LangGraph research agent + OpenLLMetry tracing

### Phase 03: Streaming + Persistence
**Goal**: Tokens stream in real-time via NATS. Registry data persisted in PostgreSQL. CRUD API works.
**Depends on**: Phase 02
**Plans**: 2 plans

Plans:
- [x] 03-01: NATS JetStream + agent-to-UI streaming pipeline
- [x] 03-02: PostgreSQL + pgvector + 4 registry tables + CRUD API + seed data

### Phase 04: Multi-Agent Workflows
**Goal**: Trigger a multi-step workflow in Chainlit, see 4 agent pods execute sequentially with per-step tracing.
**Depends on**: Phase 03
**Plans**: 2 plans

Plans:
- [ ] 04-01: Argo Workflows on Kind/GKE + agent worker pod template
- [ ] 04-02: Multiple assistants + workflow execution + Chainlit step visualization

### Phase 05: Context Engineering
**Goal**: Agents understand your repos via AST-parsed code indexes and pgvector semantic search.
**Depends on**: Phase 04
**Plans**: 4 plans

Plans:
- [x] 05-01: Repo indexing pipeline (AST parsing + embeddings + REPO_INDEX.md generation)
- [x] 05-02: code_search tool + context assembly + cross-repo dependency graph
- [x] 05-03: Multi-user repo management (Argo-based indexing, repos table, GitHub PAT auth)
- [ ] 05-04: Multi-language indexing (JS/TS/Go) via tree-sitter

### Phase 06: Model Comparison + Eval
**Goal**: Run same task on Claude vs Gemini, see side-by-side scores in Chainlit, evaluate with golden tests.
**Depends on**: Phase 05
**Plans**: 2 plans

Plans:
- [ ] 06-01: Multi-model LiteLLM config + comparison workflow + Chainlit comparison view
- [ ] 06-02: Golden test framework + Prometheus metrics + Grafana model comparison dashboard

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 01. Foundation + Observability | 3/3 | Complete | 2026-04-01 |
| 02. Chat UI + First Agent | 2/2 | Complete | 2026-04-01 |
| 03. Streaming + Persistence | 2/2 | Complete | 2026-04-01 |
| 04. Multi-Agent Workflows | 2/2 | Complete | 2026-04-01 |
| 05. Context Engineering | 3/4 | In progress | 2026-04-03 |
| 06. Model Comparison + Eval | 0/2 | Not started | - |
