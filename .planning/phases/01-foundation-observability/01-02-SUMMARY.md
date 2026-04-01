---
phase: 01-foundation-observability
plan: 01-02
status: complete
completed: 2026-04-01
---

# Summary: 01-02 Observability Stack — Prometheus/Grafana, Jaeger, Langfuse on Kind

## What Was Accomplished

All three tasks completed successfully with all three UIs verified by user:

1. **Prometheus + Grafana** via `kube-prometheus-stack` Helm chart — Grafana accessible at `localhost:3000`, pre-loaded with 25+ Kubernetes dashboards (kubernetes-mixin + node-exporter-mixin). Prometheus scraping K8s metrics with 24h retention.

2. **Jaeger all-in-one** — Jaeger UI accessible at `localhost:16686`, OTLP endpoints ready on ports 4317 (gRPC) and 4318 (HTTP) for agent traces in Phase 02.

3. **Langfuse self-hosted v2 + PostgreSQL StatefulSet** — Langfuse accessible at `localhost:3001`, project `null-realm` created, API keys generated. PostgreSQL 16 with pgvector extension running as shared StatefulSet.

## Files Created

```
infra/k8s/helm-values/prometheus-grafana.yaml   # kube-prometheus-stack values (NodePort 30002, 24h retention)
infra/k8s/system/jaeger/deployment.yaml         # Jaeger all-in-one (OTLP enabled)
infra/k8s/system/jaeger/service.yaml            # NodePort 30003 → hostPort 16686
infra/k8s/system/postgres/statefulset.yaml      # PostgreSQL 16 + pgvector, 1Gi PVC
infra/k8s/system/postgres/service.yaml          # ClusterIP on port 5432
infra/k8s/system/langfuse/deployment.yaml       # Langfuse v2, connects to postgres
infra/k8s/system/langfuse/service.yaml          # NodePort 30004 → hostPort 3001
```

## Files Modified

```
tasks.py    # Added deploy_observability task (Helm + kubectl apply for all 3 services)
```

## Port Mapping Summary

| Service    | Kind NodePort | Host Port | URL                   |
|------------|--------------|-----------|------------------------|
| Grafana    | 30002        | 3000      | http://localhost:3000  |
| Jaeger UI  | 30003        | 16686     | http://localhost:16686 |
| Langfuse   | 30004        | 3001      | http://localhost:3001  |

## Internal Service Endpoints (for agents)

| Service              | Cluster DNS                                      | Port  |
|----------------------|--------------------------------------------------|-------|
| Jaeger OTLP gRPC     | jaeger.null-realm.svc.cluster.local              | 4317  |
| Jaeger OTLP HTTP     | jaeger.null-realm.svc.cluster.local              | 4318  |
| Langfuse             | langfuse.null-realm.svc.cluster.local            | 3000  |
| PostgreSQL           | postgres.null-realm.svc.cluster.local            | 5432  |

## Decisions Made

- **Jaeger**: Used simple Deployment (not Jaeger Operator) — correct for dev, no unnecessary complexity.
- **PostgreSQL**: Shared `pgvector/pgvector:pg16` StatefulSet — used by Langfuse now, will also be used by the app in Phase 03.
- **Langfuse v2**: Single-container image (`langfuse/langfuse:2`) — DB migrations run automatically on startup.
- **No Grafana persistence**: `enabled: false` for local dev to keep it lightweight.
- **alertmanager disabled**: Not needed for local dev observability.

## Deviations from Plan

- Grafana NodePort set to **30002** (not 30300 as suggested in plan) — matched to the existing kind-config.yaml mapping where `containerPort: 30002 → hostPort: 3000`.
- Jaeger NodePort set to **30003** (derived from kind-config.yaml `containerPort: 30003 → hostPort: 16686`).
- Langfuse NodePort set to **30004** (derived from kind-config.yaml `containerPort: 30004 → hostPort: 3001`).
- Jaeger service uses a single `NodePort` type (not mixed NodePort/ClusterIP per-port, which K8s doesn't support). All ports accessible via the same service.

## Verification Results

- [x] Grafana accessible at `localhost:3000` — 25+ K8s dashboards visible, scraping live cluster metrics
- [x] Jaeger accessible at `localhost:16686` — UI loads, ready to receive OTLP traces
- [x] Langfuse accessible at `localhost:3001` — project `null-realm` created, API keys generated
- [x] All 8 pods Running in `null-realm` namespace

## Pod Status at Completion

```
jaeger                                    1/1  Running
langfuse                                  1/1  Running
postgres                                  1/1  Running
prometheus-grafana                        3/3  Running
prometheus-kube-prometheus-operator       1/1  Running
prometheus-kube-state-metrics             1/1  Running
prometheus-prometheus-kube-prometheus-0   2/2  Running
prometheus-prometheus-node-exporter       1/1  Running
```

## Langfuse Project Info

- Project name: `null-realm`
- Host: `http://localhost:3001`
- Keys: Generated via UI (API Keys section) — store in `.env` as `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`

## Next Step

**01-03**: Provision GKE Autopilot cluster via Pulumi Python, set up Cloud Build CI/CD, and deploy the observability stack to GKE with Traefik ingress + OAuth2 Proxy authentication.
