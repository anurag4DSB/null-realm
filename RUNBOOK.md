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

### Set Pulumi secrets (one-time, before first `pulumi-up`)

```bash
cd infra/pulumi
# Database password (stored encrypted in Pulumi.dev.yaml, never in plaintext)
PULUMI_CONFIG_PASSPHRASE="" pulumi config set --secret db_password <your-password>
```

### Populate GCP Secret Manager (one-time, after `pulumi-up`)

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

## Recreating Ephemeral Resources

These resources are NOT in the repo (they contain secrets or are created in UIs).
If the GKE cluster is destroyed and recreated, follow these steps.

### 1. K8s Secret: `llm-api-keys` (null-realm namespace)

**What**: API keys for LLM calls and observability tracing.
**Used by**: LiteLLM (Anthropic key), API server (Langfuse keys).

```bash
CTX=gke_helpful-rope-230010_europe-west1_null-realm

kubectl create secret generic llm-api-keys \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-..." \
  --from-literal=LANGFUSE_SECRET_KEY="sk-lf-..." \
  --from-literal=LANGFUSE_PUBLIC_KEY="pk-lf-..." \
  --from-literal=LANGFUSE_HOST="http://langfuse.null-realm.svc.cluster.local:3000" \
  -n null-realm --context $CTX
```

**Where to get the values**: `.secrets.local.md` in repo root (gitignored).

### 2. K8s Secret: `oauth2-proxy-secrets` (null-realm namespace)

**What**: Google OAuth credentials for protecting GKE services.
**Used by**: OAuth2 Proxy (Google login for all subdomains).

```bash
kubectl create secret generic oauth2-proxy-secrets \
  --from-literal=client-id="<Google OAuth Client ID>" \
  --from-literal=client-secret="<Google OAuth Client Secret>" \
  --from-literal=cookie-secret="$(python3 -c 'import secrets; print(secrets.token_hex(16))')" \
  -n null-realm --context $CTX
```

**Where to get the values**:
- Client ID/Secret: GCP Console → APIs & Services → Credentials → `null-realm` OAuth client
- Cookie secret: auto-generated (any 32-char hex string)

### 3. Langfuse account + project

**What**: Langfuse needs a user account and project to generate API keys.
**Affects**: LLM trace visibility in Langfuse UI.

1. Open Langfuse UI (GKE: `34.53.165.155.nip.io`, local: `localhost:3001`)
2. Sign up (email/password, anything works for self-hosted)
3. Create org + project named `null-realm`
4. Go to API Keys → Create new key
5. Copy Public Key + Secret Key → update `llm-api-keys` K8s secret (step 1)

### 4. Google OAuth redirect URI

**What**: Google requires a redirect URI for OAuth login flow.
**Affects**: Login won't work without this.

1. GCP Console → APIs & Services → Credentials → `null-realm` OAuth client
2. Add redirect URI: `http://34.53.165.155.nip.io/oauth2/callback`
   (replace IP if Traefik's LoadBalancer IP changed)

### 5. Seed registry data

**What**: Tools, prompts, assistants, workflows in PostgreSQL.
**How**: Run from inside the api-server pod:

```bash
kubectl exec -n null-realm deploy/api-server --context $CTX -- \
  uv run python -m nullrealm.registry.seed
```

### 6. Apply non-Helm K8s resources

Some resources are in the repo but not auto-applied by Helm:

```bash
# Argo RBAC for agent pods
kubectl apply -f infra/k8s/argo-templates/rbac.yaml --context $CTX

# Argo WorkflowTemplate (GKE version)
kubectl apply -f infra/k8s/gke/argo-templates/agent-worker.yaml --context $CTX

# Argo metrics service + ServiceMonitor
kubectl apply -f infra/k8s/gke/argo-metrics.yaml --context $CTX

# Extra Grafana datasources (Jaeger + Langfuse)
kubectl apply -f infra/k8s/gke/grafana-datasources.yaml --context $CTX

# Auth redirect nginx
kubectl apply -f infra/k8s/gke/auth-redirect/ --context $CTX

# OAuth2 Proxy
kubectl apply -f infra/k8s/gke/oauth2-proxy/deployment.yaml --context $CTX

# Traefik IngressRoutes
kubectl apply -f infra/k8s/gke/ingress/ --context $CTX

# All GKE app deployments
kubectl apply -f infra/k8s/gke/api-server/deployment.yaml --context $CTX
kubectl apply -f infra/k8s/gke/chainlit/deployment.yaml --context $CTX
kubectl apply -f infra/k8s/gke/litellm/deployment.yaml --context $CTX
kubectl apply -f infra/k8s/gke/jaeger/ --context $CTX
kubectl apply -f infra/k8s/gke/langfuse/ --context $CTX
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

---

## Knowledge Graph — Re-Index All Repos

When the parser or indexing pipeline changes, re-index everything from scratch.

### Prerequisites
- Worker and MCP images built and pushed with latest code
- MCP server restarted on GKE
- MCP connected (run `/mcp` in Claude Code)
- GITHUB_TOKEN secret exists in `null-realm-agents` namespace for private repos

### Step 1: Delete all existing indexes

```
# Via MCP tools (in Claude Code):
delete_repo_index("cloudserver")
delete_repo_index("Arsenal")
delete_repo_index("backbeat")
delete_repo_index("vault")
delete_repo_index("MetaData")
delete_repo_index("utapi")
delete_repo_index("scuba")
delete_repo_index("bucketclient")
delete_repo_index("vaultclient")
delete_repo_index("scubaclient")
delete_repo_index("sproxydclient")
delete_repo_index("Federation")
```

### Step 2: Re-index all 12 repos (parallel Argo workflows)

```
# Code repos (11):
index_repo("https://github.com/scality/cloudserver", branch="development/9.2")
index_repo("https://github.com/scality/Arsenal", branch="development/8.3")
index_repo("https://github.com/scality/backbeat", branch="development/9.3")
index_repo("https://github.com/scality/vault", branch="development/7", auth_type="token")
index_repo("https://github.com/scality/MetaData", branch="development/9", auth_type="token")
index_repo("https://github.com/scality/utapi", branch="development/8.2")
index_repo("https://github.com/scality/scuba", branch="main", auth_type="token")
index_repo("https://github.com/scality/bucketclient", branch="development/8.2")
index_repo("https://github.com/scality/vaultclient", branch="development/8.5")
index_repo("https://github.com/scality/scubaclient", branch="development/1.1")
index_repo("https://github.com/scality/sproxydclient", branch="development/8.2")

# Federation (config mode):
index_federation_repo("https://github.com/scality/Federation", branch="development/10", auth_type="token")
```

All 12 run as parallel Argo workflows on GKE. Takes ~5 min total.

### Step 3: Verify all repos are ready

```
list_repos()
# All 12 should show status: ready
```

### Step 4: Create cross-repo XREF edges

```
link_repos()
# Creates XREF edges across repos using dep_map from package.json
```

### Step 5: Verify cross-repo linking

```
service_topology()     # Shows service-to-service connections
graph_query("MetadataWrapper", depth=2)  # Should show Arsenal + callers from other repos
code_search("bucket policy validation")  # Should return JS code from cloudserver
```

### Step 6: Restart visualization apps (optional)

```bash
kubectl scale deploy/spotlight deploy/atlas deploy/projector --replicas=1 \
  -n null-realm --context gke_helpful-rope-230010_europe-west1_null-realm
```

### Notes
- If Neo4j crashes during parallel indexing (>10 concurrent workflows), re-submit the failed repos
- Private repos (vault, MetaData, scuba, Federation) need `auth_type="token"`
- Federation uses `--mode federation` (text chunking), all others use `--mode code` (tree-sitter)
- Cloudserver branch is `development/9.2` (NOT `main`)
- Scuba branch is `main` (not `development/*`)
