# Null Realm

**One-liner**: A learning lab for building, deploying, and evaluating multi-agent systems on GKE — model-agnostic, fully traced, production-grade.

## Problem

Agent engineering is learned by building, not reading. We need a real multi-agent system where:
- Single-responsibility agents collaborate via orchestrated workflows
- Any LLM (Claude, Gemini, Kimi) can power any agent — swap models per agent
- Every request, handoff, and tool call is traced end-to-end
- Models are compared side-by-side on real tasks with scored evaluations

No vendor lock-in. No toy demos. A real lab on real infrastructure.

## Success Criteria

How we know it worked:

- [ ] Chat with a research agent in Chainlit that reads code, does RAG, and streams responses
- [ ] Multi-step workflow (research → plan → implement → review) executes across agent pods
- [ ] Same task runs on Claude vs Gemini with LLM-judge scoring and side-by-side comparison in UI
- [ ] Full trace visible in Langfuse (LLM calls, tokens, cost) and Jaeger (distributed spans)
- [ ] Grafana dashboards show agent metrics, model costs, and K8s health
- [ ] Everything runs on local Kind cluster AND auto-deploys to GKE on push to main

## Constraints

- **GCP only**: GKE Autopilot, Cloud SQL, Artifact Registry, Secret Manager (project: `helpful-rope-230010`)
- **Python**: Backend, agents, and tooling all Python 3.14+ with uv
- **Open source stack**: Argo Workflows, LangGraph, LiteLLM, NATS, Chainlit, Langfuse, Prometheus/Grafana
- **IaC via Pulumi Python**: No Terraform — real Python code for infrastructure
- **Visual first**: Always have something to see — observability before app, UI before backend
- **Local first, cloud always**: Every step works on local Kind, every push deploys to GKE

## Out of Scope

- Custom frontend (Chainlit is the UI, not a custom Next.js app)
- GPU workloads or fine-tuning (this is an inference lab)
- Multi-tenant auth or user management
- Mobile or desktop clients
