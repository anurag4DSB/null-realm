---
phase: 01-foundation-observability
plan: 01-03
status: complete
completed: 2026-04-01
---

# Summary: 01-03 GKE Autopilot via Pulumi + CI/CD + Observability on GKE

## What Was Accomplished

All four tasks completed:

1. **Pulumi Python GCP infrastructure** — VPC, GKE Autopilot, Cloud SQL PostgreSQL 16, Artifact Registry, Secret Manager, IAM, Cloud NAT. All resources labeled `user: anurag`, `project: null-realm` in `europe-west1`.

2. **Cloud Build CI/CD** — `cloudbuild.yaml` builds 3 images, pushes to Artifact Registry, deploys to GKE. Trigger creation deferred until GitHub App is connected (manual step in GCP Console).

3. **Observability on GKE** — Prometheus/Grafana (Helm), Jaeger, Langfuse all deployed. Langfuse connects to Cloud SQL via private IP (10.5.0.3). All 6 pods running and verified.

4. **Traefik + OAuth2 Proxy** — Traefik v3.6 with LoadBalancer (external IP: 34.53.165.155). IngressRoutes for Grafana, Jaeger, Langfuse with ForwardAuth middleware. OAuth2 Proxy deployment ready but needs credentials applied.

## Files Created

```
infra/pulumi/__main__.py                              # Pulumi entrypoint
infra/pulumi/networking.py                            # VPC, subnet, VPC peering, Cloud NAT
infra/pulumi/gke.py                                   # GKE Autopilot cluster
infra/pulumi/cloudsql.py                              # Cloud SQL PostgreSQL 16
infra/pulumi/registry.py                              # Artifact Registry
infra/pulumi/iam.py                                   # Service accounts + IAM bindings
infra/pulumi/secrets.py                               # Secret Manager secrets
infra/pulumi/cloudbuild.py                            # Cloud Build trigger (conditional)
infra/pulumi/requirements.txt                         # Python deps (pulumi, pulumi-gcp)
infra/pulumi/Pulumi.yaml                              # Pulumi project config
infra/pulumi/Pulumi.dev.yaml                          # Dev stack config (encrypted secrets)
cloudbuild.yaml                                       # CI/CD pipeline (3 images + deploy)
infra/k8s/helm-values/prometheus-grafana-gke.yaml     # Helm values for GKE (ClusterIP, no node-exporter)
infra/k8s/helm-values/traefik-gke.yaml                # Traefik Helm values
infra/k8s/gke/jaeger/deployment.yaml                  # Jaeger all-in-one for GKE
infra/k8s/gke/jaeger/service.yaml                     # Jaeger ClusterIP service
infra/k8s/gke/langfuse/deployment.yaml                # Langfuse v2 → Cloud SQL
infra/k8s/gke/langfuse/service.yaml                   # Langfuse ClusterIP service
infra/k8s/gke/oauth2-proxy/deployment.yaml            # OAuth2 Proxy (Google provider)
infra/k8s/gke/oauth2-proxy/service.yaml               # OAuth2 Proxy ClusterIP
infra/k8s/gke/oauth2-proxy/secret.yaml                # Placeholder — fill before deploy
infra/k8s/gke/ingress/middleware.yaml                  # ForwardAuth → OAuth2 Proxy
infra/k8s/gke/ingress/routes.yaml                     # IngressRoutes for all services
RUNBOOK.md                                            # All commands documented
.secrets.local.md                                     # Local-only credential reference (gitignored)
```

## Files Modified

```
tasks.py              # Added: pulumi-up, pulumi-destroy, get-gke-credentials,
                      #        sql-stop, sql-start, gcp-status
.gitignore            # Added .secrets.local.md
.planning/ROADMAP.md  # Updated region to europe-west1, progress to 3/3
.planning/COSTS.md    # Updated region references
```

## GCP Resources (Pulumi-managed, 23 total)

| Resource | Name | Region |
|----------|------|--------|
| GKE Autopilot | null-realm | europe-west1 |
| Cloud SQL PostgreSQL 16 | null-realm-db | europe-west1 |
| Artifact Registry | null-realm | europe-west1 |
| VPC | null-realm-vpc | global |
| Subnet | null-realm-subnet | europe-west1 |
| Cloud Router | null-realm-router | europe-west1 |
| Cloud NAT | null-realm-nat | europe-west1 |
| Service Accounts | null-realm-gke, null-realm-cloudbuild | — |
| Secrets | ANTHROPIC_API_KEY, DATABASE_URL, OAUTH2_* (5) | global |
| VPC Peering | null-realm-vpc-connection | — |

## GKE Pod Status

```
jaeger                                    1/1  Running
langfuse                                  1/1  Running
prometheus-grafana                        3/3  Running
prometheus-kube-prometheus-operator       1/1  Running
prometheus-kube-state-metrics             1/1  Running
prometheus-prometheus-0                   2/2  Running
traefik                                   1/1  Running
```

## Deviations from Plan

1. **Region changed**: `us-central1` → `europe-west1` (user in Paris, lower latency)
2. **Cloud NAT added**: Private GKE nodes can't pull external images without NAT — not in original plan
3. **Node-exporter disabled**: GKE Autopilot blocks hostPID/hostNetwork required by node-exporter DaemonSet
4. **Subnet CIDRs changed**: `10.4.0.0/16` + `10.5.0.0/20` → `10.100.0.0/16` + `10.101.0.0/20` (europe-west1 reserved range conflict)
5. **DB password moved to Pulumi secret**: Was hardcoded in cloudsql.py, now `pulumi config require_secret("db_password")`
6. **GCP labels added**: All resources tagged `user: anurag`, `project: null-realm`
7. **Cloud Build trigger deferred**: GitHub App not connected yet — trigger guarded by `github_connected` config flag

## Manual Steps Remaining

1. **Fill OAuth2 credentials** in `infra/k8s/gke/oauth2-proxy/secret.yaml` and apply
2. **Update Google OAuth redirect URI** to `http://34.53.165.155/oauth2/callback`
3. **Connect GitHub** to Cloud Build via GCP Console, then `pulumi config set github_connected true && pulumi up`
4. **Populate Secret Manager** values (see RUNBOOK.md)

## Next Step

**Phase 02**: Chat UI + First Agent — Chainlit + FastAPI + LiteLLM + LangGraph agent with tracing.
