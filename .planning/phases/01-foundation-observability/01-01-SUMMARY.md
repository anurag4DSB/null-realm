---
phase: 01-foundation-observability
plan: 01-01
status: complete
completed: 2026-04-01
---

# Summary: 01-01 Project Scaffold + Kind Cluster + Container Build Pipeline

## What Was Accomplished

All three tasks completed successfully:

1. **Python project scaffold** -- uv-managed project with all dependencies (FastAPI, LangGraph, LiteLLM, Chainlit, SQLAlchemy, NATS, OpenTelemetry, Pydantic Settings). 177 packages installed and locked.

2. **Dockerfiles + Invoke tasks + Kind cluster** -- Three Dockerfiles (api, worker, ui) using python:3.12-slim + uv. Invoke tasks.py provides `kind-up`, `kind-down`, `build`, `load-images`, `deploy-local`, and `dev` commands. Kind cluster running with port mappings and both namespaces created.

3. **Container images built and loaded** -- All three images (null-realm-api, null-realm-worker, null-realm-ui) build successfully and are loaded into the Kind cluster.

## Files Created

```
pyproject.toml                          # uv-managed Python project, >=3.12
uv.lock                                 # Locked dependencies (auto-generated)
nullrealm/__init__.py                   # Package init with __version__
nullrealm/config.py                     # Pydantic Settings (env var loading)
nullrealm/main.py                       # FastAPI app with GET /health
nullrealm/worker/__init__.py            # Worker package init
nullrealm/worker/main.py                # Worker entry point (placeholder)
ui/app.py                               # Chainlit echo app (placeholder)
.env.example                            # All required env vars documented
docker-compose.yaml                     # Local dev infra (postgres, nats, jaeger, langfuse, grafana, prometheus)
Dockerfile.api                          # API server image
Dockerfile.worker                       # Worker image
Dockerfile.ui                           # Chainlit UI image
tasks.py                                # Invoke task runner
scripts/kind-config.yaml                # Kind cluster config with port mappings
infra/k8s/base/namespace.yaml           # null-realm + null-realm-agents namespaces
infra/prometheus/prometheus.yaml         # Prometheus scrape config for docker-compose
```

## Decisions Made

- **Python version**: `requires-python = ">=3.12"` in pyproject.toml. Local dev uses 3.14 (installed via uv), Docker images use python:3.12-slim for stability.
- **Build backend**: Hatchling with explicit `packages = ["nullrealm"]` since the project name `null-realm` doesn't match the package directory `nullrealm`.
- **Docker images use uv**: All Dockerfiles use `COPY --from=ghcr.io/astral-sh/uv:latest` for fast, reproducible installs inside containers.
- **Kind port mappings**: Use NodePort range (30000-30004) mapped to host ports (8000, 8501, 3000, 16686, 3001).

## Deviations from Plan

- Added `README.md` to Dockerfile COPY commands -- Hatchling requires it since `readme = "README.md"` is in pyproject.toml.
- Added `[tool.hatch.build.targets.wheel] packages = ["nullrealm"]` -- needed because project name (`null-realm`) differs from package dir (`nullrealm`).
- Created `nullrealm/worker/` package with placeholder main.py so Dockerfile.worker has a valid entry point.
- Created `infra/prometheus/prometheus.yaml` so docker-compose.yaml works out of the box.

## Issues Encountered

- **Hatchling build failure**: Initial `uv sync` failed because hatchling couldn't find the `null_realm` directory (expected from project name). Fixed by adding explicit `packages` config.
- **Docker build failure**: First Docker build failed because `README.md` wasn't copied into the image. Fixed by adding it to the COPY command.

## Verification Results

- [x] `uv sync` succeeds
- [x] Kind cluster running (`kubectl get nodes` shows Ready)
- [x] Both namespaces exist (`null-realm`, `null-realm-agents`)
- [x] All 3 Docker images build and appear in `docker images`
- [x] Images loaded into Kind cluster

## Next Step

**01-02**: Deploy observability stack (Prometheus/Grafana, Jaeger, Langfuse) on the Kind cluster using Helm charts.
