---
phase: 02-chat-ui-agent
plan: 02-02
status: complete
completed: 2026-04-01
---

# Summary: 02-02 LiteLLM Proxy + LangGraph Agent + OpenLLMetry Tracing

## What Was Accomplished

1. **LiteLLM Proxy** — deployed on Kind with `claude-sonnet` model alias mapping to `anthropic/claude-sonnet-4-20250514`. Runs as ClusterIP service on port 4000. Required 2Gi memory (OOMKills at lower).

2. **LangGraph ReAct agent** — StateGraph with LLM call → tool check → tool execute → loop/respond. Uses `ChatOpenAI` pointing to LiteLLM proxy with 120s timeout and 2 retries. Agent singleton for connection reuse. Includes `file_read` tool.

3. **OpenLLMetry tracing** — OTLP exporter configured for Jaeger, Traceloop SDK for automatic LLM instrumentation. Langfuse callback handler ready (needs LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in env).

4. **End-to-end pipeline verified**: Chainlit → WebSocket → FastAPI → LangGraph → LiteLLM → Claude → response.

## Files Created

```
infra/k8s/system/litellm/deployment.yaml       # LiteLLM proxy (2Gi memory)
infra/k8s/system/litellm/litellm-config.yaml   # ConfigMap: claude-sonnet alias
infra/k8s/system/litellm/service.yaml          # ClusterIP on port 4000
nullrealm/worker/langgraph_agent.py            # LangGraph ReAct agent
nullrealm/worker/bootstrap.py                  # Agent factory with config
nullrealm/tools/__init__.py
nullrealm/tools/base.py                        # BaseTool ABC
nullrealm/tools/builtins/__init__.py
nullrealm/tools/builtins/file_read.py          # File read tool
nullrealm/observability/__init__.py
nullrealm/observability/tracing.py             # OTLP + Traceloop + Langfuse init
```

## Files Modified

```
nullrealm/api/websocket.py    # Echo → agent execution
nullrealm/main.py             # Added lifespan with init_tracing()
nullrealm/config.py           # Added otel/litellm settings
pyproject.toml                # Added langchain-core, langchain-openai, traceloop-sdk, langfuse
.env.example                  # Added OTEL/LITELLM/LANGFUSE vars
.gitignore                    # Added .chainlit/ and chainlit.md
```

## Deviations

- LiteLLM memory bumped to 2Gi (image is heavy, OOMKills at 512Mi/1Gi)
- K8s secret limited to ANTHROPIC_API_KEY only (LiteLLM crashed with DATABASE_URL from full .env)
- Tracing to Jaeger needs OTEL_EXPORTER_OTLP_ENDPOINT set to K8s service DNS in deployment env vars (TODO for next iteration)
- Python 3.14 local incompatibility with Chainlit (anyio issue) — works in Docker (3.12)

## Known Issues

- API server deployment needs env vars for OTEL/LITELLM/LANGFUSE endpoints (currently using defaults which point to localhost inside the pod)
- Langfuse tracing requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to be set

## Next Step

**Phase 03**: Streaming + Persistence — NATS real-time streaming + PostgreSQL registry CRUD.
