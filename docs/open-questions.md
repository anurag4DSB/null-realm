# Open Questions & Pending Decisions

Track items that came up during development but aren't blocking — revisit when relevant.

---

## UI / Chainlit Customization

**Config file**: `.chainlit/config.toml`

### Auto-scroll behavior (noticed Phase 03)
When a second message is sent, the viewport jumps to show the new question at the top. History is preserved (scroll up to see it), but the jump feels abrupt.

**Options**:
- `user_message_autoscroll = false` → viewport stays where you are
- `assistant_message_autoscroll = false` → doesn't jump during streaming
- Keep defaults (current) — this is how ChatGPT/Claude.ai behave

**Decision**: TBD — try toggling and see what feels better.

### Branding & theme
- `name = "Assistant"` → should change to `"Null Realm"` or project-specific name
- `default_theme = "dark"` → currently uses browser default, could force dark
- `layout = "wide"` → wider chat area, good for code/tool output
- `cot = "full"` → already shows chain-of-thought/tool steps (keep)
- `custom_css` → can point to `/public/custom.css` for deeper styling
- `logo_file_url` → add a Null Realm logo

**Decision**: Low priority. Apply branding when the core features are stable.

### Custom CSS ideas
- Style tool steps differently (highlight file_read, bash, etc.)
- Code block syntax highlighting theme
- Compact message spacing for longer conversations

---

## GKE Deployment Cadence

### GKE deployment cadence

**Decision (resolved)**: Deploy to GKE after every phase (or within phases when meaningful changes land). Manual deploy via `docker buildx --platform linux/amd64 --push` + `kubectl apply`. Cloud Build trigger is NOT connected (company GCP + personal repo) — don't assume it in plans.

---

## Argo Workflows on GKE

Currently only deployed on Kind. GKE needs:
- Argo Helm install in `null-realm` namespace (controller + server)
- Worker images from Artifact Registry (not `imagePullPolicy: Never`)
- RBAC for `null-realm-agents` namespace
- WorkflowTemplate with GKE-specific image refs and resource requests
- Cost: ~$1-2/day extra (controller + server pods on Autopilot)

**When**: After Phase 05 or when we want to demo multi-agent workflows on GKE. Not blocking — workflows run fine on Kind.

---

## Langfuse v3 upgrade

Currently on Langfuse v2 (single container, `langfuse/langfuse:2`). v3 is a major rewrite with:
- Separate web + worker processes (still single Docker image option)
- Improved analytics and dashboard
- Better trace visualization
- Breaking API changes possible

**When**: Phase 06 (model comparison + eval) — the improved analytics would benefit the comparison dashboards. Upgrading mid-build risks breaking the tracing pipeline.

**What's needed**:
- Test v3 image locally first (`langfuse/langfuse:3`)
- Check if `NEXTAUTH_*` env vars still work or changed
- Verify LiteLLM's `success_callback: ["langfuse"]` is compatible
- Update both Kind and GKE deployments
- Re-create Langfuse account/project (v3 may use different DB schema)

---

## Per-service trace names

Currently all services report as `null-realm` in Jaeger. Should differentiate:
- `null-realm.api` — FastAPI server
- `null-realm.worker.research` — research agent pod
- `null-realm.worker.planner` — planner agent pod
- etc.

**When**: Phase 06 — when building the comparison dashboard, per-service filtering becomes important.
**How**: Pass `service.name` dynamically in `init_tracing()` based on `ASSISTANT_NAME` env var or service role.

---

## Argo Grafana dashboard uses v3 metric names

The pre-built dashboard (`grafana-dashboards-argo.json`) was written for Argo v3 metrics. Argo v4 renamed metrics:
- v3: `argo_workflows_count` → v4: `argo_workflows_gauge`
- v3: `argo_workflows_pods_count` → v4: different structure

Data IS in Prometheus (verified via Explore). Dashboard panels just need query updates.

**When**: Phase 06 — build all custom dashboards together (Argo, LLM costs, model comparison).

---

## Automatic re-indexing on PR merge (partially addressed)

**What exists now**: On-demand indexing via the `index_repo` MCP tool. Any MCP client (Claude Code, Cursor, etc.) can trigger a full re-index by calling `index_repo(url, branch)`. Re-indexing is idempotent -- old data is replaced. The `delete_repo_index` tool also exists for clean removal.

**What's still missing**: Automatic webhook-triggered re-indexing on PR merge. The manual/on-demand path works but requires a human to remember to re-index after code changes.

**Remaining architecture** (future):
```
GitHub PR merged → Webhook → Cloud Run/K8s Job → 
  1. git pull changed files
  2. Re-parse AST for changed files only (incremental)
  3. Re-embed changed chunks
  4. Update Neo4j graph edges for changed files
  5. Re-run PaCMAP on full embedding set
  6. Update visualizations
```

**Options**:
- GitHub webhook → Cloud Run function (serverless, pay-per-invocation)
- Argo Events → Argo Workflow (already have Argo, native K8s)
- GitHub Actions → call GKE API (simplest, but requires GitHub-GKE auth)

**When**: Post-v1.0, after Phase 06. Incremental re-indexing (changed files only) is the main gap.

---

## API server hangs on GKE after Phase 05 deps added

The API server Docker image installs ALL pyproject.toml deps including sentence-transformers (~500MB), google-cloud-aiplatform, pacmap, plotly, streamlit. These are needed by the MCP server and viz tools but NOT by the API server.

**Symptom**: `uv run uvicorn nullrealm.main:app` hangs after `uv sync` — never starts.
**Root cause**: Heavy deps (2GB+) in a pod with limited memory. Or `uv run` is recompiling/downloading at startup.
**Quick fix**: Bump API server memory to 3Gi.
**Proper fix**: Separate dependency groups in pyproject.toml:
```toml
[project.optional-dependencies]
api = ["fastapi", "uvicorn", "sqlalchemy", "asyncpg", ...]  # lightweight
ml = ["sentence-transformers", "google-cloud-aiplatform", ...]  # heavy
viz = ["pacmap", "plotly", "streamlit", ...]  # viz only
```
Then `Dockerfile.api` installs only `uv sync --extra api`, not everything.

**When**: Next session, before Phase 06.

---

## invoke binary missing

`uv run invoke build` stopped working — the `invoke` binary isn't found in the venv. Direct `docker build` works. Need to debug why `invoke` disappeared from the path.

**Workaround**: Use `docker build -t null-realm-api:latest -f Dockerfile.api .` directly.
**TODO**: Fix `tasks.py` / `invoke` installation.

---

> Add new items here as they come up. Move to `docs/architecture/decisions.md` once a decision is made.
