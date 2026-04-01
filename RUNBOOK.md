# Null Realm — Runbook

Quick reference for every command you'll need day-to-day.
All `invoke` tasks live in `tasks.py` and run via `uv run invoke <task>`.

> **Tip**: Add `alias inv="uv run invoke"` to `~/.zshrc` so you can type `inv gcp-status` instead.

---

## Prerequisites

```bash
# Required tools
brew install kind helm kubectl pulumi
brew install --cask google-cloud-sdk   # gcloud

# Python dependencies (run once after cloning)
uv sync

# Authenticate gcloud
gcloud auth login
gcloud config set project helpful-rope-230010

# Pulumi local state (run once)
pulumi login --local
```

---

## Local Development (Kind cluster)

| Command | What it does |
|---------|-------------|
| `uv run invoke kind-up` | Create local Kind cluster + namespaces |
| `uv run invoke build` | Build all 3 Docker images (api, worker, ui) |
| `uv run invoke build --service=api` | Build one image |
| `uv run invoke load-images` | Load images into Kind |
| `uv run invoke deploy-local` | Apply K8s manifests to Kind |
| `uv run invoke deploy-observability` | Deploy Grafana, Jaeger, Langfuse to Kind |
| `uv run invoke dev` | Full cycle: kind-up + build + load + deploy |
| `uv run invoke kind-down` | Delete Kind cluster |

### Local URLs (after `deploy-observability`)

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin |
| Jaeger | http://localhost:16686 | — |
| Langfuse | http://localhost:3001 | account you created |

---

## GCP / Cloud

### Infrastructure (Pulumi)

| Command | What it does |
|---------|-------------|
| `uv run invoke pulumi-up` | Provision / update all GCP resources |
| `uv run invoke pulumi-destroy` | **Tear down everything** — stops all billing |
| `uv run invoke get-gke-credentials` | Get kubeconfig for GKE cluster |
| `uv run invoke gcp-status` | Show all deployed GCP resources + Pulumi outputs |

### Cost control

| Command | What it does | Saves |
|---------|-------------|-------|
| `uv run invoke sql-stop` | Stop Cloud SQL (storage still billed) | ~$1.78/day |
| `uv run invoke sql-start` | Start Cloud SQL before a session | — |
| `uv run invoke pulumi-destroy` | Destroy everything | ~$5.50/day |

> See `.planning/COSTS.md` for full cost breakdown per phase.

### What Pulumi manages

All resources are tagged `project: null-realm`, `user: anurag` and live in `europe-west1`.

| Resource | Name | Purpose |
|----------|------|---------|
| GKE Autopilot | `null-realm` | Runs all workloads |
| Cloud SQL PostgreSQL 16 | `null-realm-db` | App + Langfuse database |
| Artifact Registry | `null-realm` | Docker images |
| Secret Manager | `ANTHROPIC_API_KEY`, `DATABASE_URL`, `OAUTH2_*` | Secrets |
| VPC + Subnet | `null-realm-vpc` | Private networking |

### Populate secrets (one-time, after `pulumi-up`)

```bash
# Anthropic API key
echo -n "sk-ant-..." | gcloud secrets versions add ANTHROPIC_API_KEY \
  --data-file=- --project=helpful-rope-230010

# OAuth2 Proxy client ID and secret (from GCP Console → Credentials)
echo -n "your-client-id" | gcloud secrets versions add OAUTH2_CLIENT_ID \
  --data-file=- --project=helpful-rope-230010

echo -n "your-client-secret" | gcloud secrets versions add OAUTH2_CLIENT_SECRET \
  --data-file=- --project=helpful-rope-230010

# Generate a random cookie secret (32 bytes, base64)
python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())" | \
  gcloud secrets versions add OAUTH2_COOKIE_SECRET \
    --data-file=- --project=helpful-rope-230010
```

---

## CI/CD (Cloud Build)

Trigger fires automatically on push to `main` → builds images → pushes to Artifact Registry → deploys to GKE.

### Connect GitHub (one-time manual step)

1. Go to: https://console.cloud.google.com/cloud-build/triggers/connect?project=helpful-rope-230010
2. Connect the `anurag4DSB/null-realm` repo
3. Then activate the Pulumi trigger:
   ```bash
   cd infra/pulumi
   PULUMI_CONFIG_PASSPHRASE="" pulumi config set github_connected true
   uv run invoke pulumi-up
   ```

### Manually trigger a build

```bash
gcloud builds submit --config cloudbuild.yaml --project helpful-rope-230010
```

---

## Inspection & Debugging

```bash
# All null-realm pods
kubectl get pods -n null-realm

# All GCP resources (GKE, SQL, registry, secrets)
uv run invoke gcp-status

# Grafana / Jaeger / Langfuse logs (local Kind)
kubectl logs deployment/prometheus-grafana -n null-realm
kubectl logs deployment/jaeger -n null-realm
kubectl logs deployment/langfuse -n null-realm

# GKE cluster info
gcloud container clusters describe null-realm \
  --region europe-west1 --project helpful-rope-230010

# Cloud SQL connection name (needed for Cloud SQL Auth Proxy)
gcloud sql instances describe null-realm-db \
  --project helpful-rope-230010 --format="value(connectionName)"

# Pulumi stack outputs
cd infra/pulumi && PULUMI_CONFIG_PASSPHRASE="" pulumi stack output
```

---

## Typical Session Flow

```bash
# Morning — start a session
uv run invoke sql-start           # start Cloud SQL (~30s to ready)
uv run invoke kind-up             # local cluster (if doing local work)

# ... do work, push to main for cloud deploy ...

# End of session — save money
uv run invoke sql-stop            # stop Cloud SQL
```
