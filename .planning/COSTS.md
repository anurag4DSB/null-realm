# Null Realm — GCP Cost Reference

> **Purpose**: Track expected GCP costs per phase. Intended to eventually become a cost-monitoring tool
> in Grafana (Phase 06 includes a cost dashboard).
>
> All prices are europe-west1, as of April 2026. Actual costs visible in:
> GCP Console → Billing → Reports, or `gcloud billing accounts list`.

---

## Summary by Phase

| Phase | New Resources Added | Added $/day | Cumulative $/day |
|-------|---------------------|-------------|------------------|
| 01-03 | GKE Autopilot, Cloud SQL, Artifact Registry, Cloud Build | ~$3.70 | ~$3.70 |
| 02    | No new infra (uses existing GKE pods) | ~$0.10 | ~$3.80 |
| 03    | NATS JetStream (pod on GKE) | ~$0.05 | ~$3.85 |
| 04    | Argo Workflows (pod on GKE) | ~$0.05 | ~$3.90 |
| 05    | GCS bucket (repo indexes) | ~$0.01 | ~$3.91 |
| 06    | No new infra | $0 | ~$3.91 |

**Estimated monthly (all phases, cluster always on): ~$117/month**

---

## Resource Breakdown

### GKE Autopilot Cluster

| Item | Price | Est. Usage | $/day |
|------|-------|------------|-------|
| Cluster management fee | $0.10/hr | Always on | $2.40 |
| Pod CPU (0.5 vCPU per pod, ~8 pods) | $0.0445/vCPU-hr | 4 vCPU total | $4.27 |
| Pod memory (1GB per pod, ~8 pods) | $0.00492/GB-hr | 8 GB total | $0.94 |
| **GKE subtotal** | | | **~$7.60/day** |

> **Note**: Autopilot charges per pod resource request, not per node. Costs scale with how many
> pods are running. The estimate above is for the full observability stack (Phase 01-03).
> Early phases with fewer pods will be cheaper.
>
> **Minimum (cluster only, no pods)**: $2.40/day just for the management fee.

### Cloud SQL (PostgreSQL 16)

| Item | Price | Config | $/day |
|------|-------|--------|-------|
| db-g1-small instance (1 vCPU, 1.7 GB RAM) | ~$0.05/hr | Shared core, cheapest | $1.20 |
| Storage (100 GB SSD) | $0.17/GB/month | 100 GB | $0.57 |
| Backup storage | $0.08/GB/month | ~5 GB auto backup | $0.01 |
| **Cloud SQL subtotal** | | | **~$1.78/day** |

> **Cost optimization**: Stop the instance when not learning — `gcloud sql instances patch null-realm-db --activation-policy NEVER`.
> No charge for a stopped instance (storage still billed).

### Artifact Registry

| Item | Price | Est. Usage | $/day |
|------|-------|------------|-------|
| Storage (3 images × ~500MB) | $0.10/GB/month | ~1.5 GB | $0.005 |
| Network egress (GKE pulls, same region) | Free | Same region | $0 |
| **Artifact Registry subtotal** | | | **~$0.005/day** |

### Cloud Build

| Item | Price | Est. Usage | $/day |
|------|-------|------------|-------|
| Build minutes (first 120/day free) | $0.003/min after free tier | ~10 min/push | ~$0 |
| **Cloud Build subtotal** | | | **~$0/day** (free tier covers normal use) |

### GCS (Phase 05+)

| Item | Price | Est. Usage | $/day |
|------|-------|------------|-------|
| Storage (repo indexes, JSONL files) | $0.02/GB/month | ~1 GB | $0.001 |
| **GCS subtotal** | | | **~$0.001/day** |

---

## Realistic Daily Cost Scenarios

| Scenario | $/day | $/month |
|----------|-------|---------|
| **Cluster on, no pods running** | ~$4.20 | ~$126 |
| **Phase 01-03 (observability stack only)** | ~$5.50 | ~$165 |
| **Phase 04+ (full stack, all pods)** | ~$7.70 | ~$231 |
| **Cluster stopped + Cloud SQL stopped** | ~$0.58 | ~$17 (storage only) |
| **Everything destroyed (`pulumi destroy`)** | $0 | $0 |

---

## Cost Control Commands

```bash
# Stop Cloud SQL when not learning (no instance charge, storage still billed)
gcloud sql instances patch null-realm-db \
  --activation-policy NEVER \
  --project helpful-rope-230010

# Restart Cloud SQL before a session
gcloud sql instances patch null-realm-db \
  --activation-policy ALWAYS \
  --project helpful-rope-230010

# Scale GKE to zero (delete non-essential pods)
kubectl scale deployment langfuse jaeger --replicas=0 -n null-realm

# Full teardown (destroys everything, $0 cost)
cd infra/pulumi && pulumi destroy --yes

# Rebuild from scratch
cd infra/pulumi && pulumi up --yes
```

---

## Phase 06: Cost Dashboard (Planned)

When Phase 06 is complete, Grafana will show:
- **Per-model cost** (tokens × price per token for Claude vs Gemini)
- **GKE pod cost** (CPU + memory × GKE price)
- **Total spend today / this week / this month**
- **Cost per agent workflow run**

Metrics will come from:
- `nullrealm/observability/cost_tracker.py` — tracks LLM token costs
- Prometheus node-exporter — GKE resource usage
- GCP Billing export to BigQuery (optional, Phase 06)

---

## Free Tier / Always-Free Resources

| Resource | Free Tier |
|----------|-----------|
| Cloud Build | 120 build-minutes/day |
| Artifact Registry | 0.5 GB/month storage |
| GCS | 5 GB/month storage |
| Cloud Logging | 50 GB/month ingestion |
| Secret Manager | 6 secret versions/month, 10K access ops |

---

> **Last updated**: 2026-04-01 (Phase 01-03 setup)
> **Update this file** when new resources are provisioned in each phase.
