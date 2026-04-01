---
phase: 04-multi-agent-workflows
plan: 04-01
status: complete
completed: 2026-04-01
---

# Summary: 04-01 Argo Workflows + Agent Worker Pod Template

## What Was Accomplished

1. **Argo Workflows v4.0.3 on Kind and GKE** -- Deployed via Helm with custom values. Argo server UI accessible at localhost:2746 (Kind) and argo.34.53.165.155.nip.io (GKE). Workflow controller manages agent pods in `null-realm-agents` namespace.

2. **Agent worker WorkflowTemplate** -- Parameterized template accepting `assistant_name`, `session_id`, `task_input`, `msg_id`. Runs null-realm-worker image with full env var configuration (NATS_URL, DATABASE_URL, LITELLM_URL, LANGFUSE keys).

3. **ArgoClient** -- Async client wrapping the Argo REST API. Methods: `submit_workflow(template, params)`, `get_workflow_status(workflow_id)`. Uses httpx for async HTTP calls.

4. **RBAC for null-realm-agents** -- ServiceAccount, Role, and RoleBinding for Argo to manage pods in the `null-realm-agents` namespace.

5. **Worker bootstrap with tracing** -- Worker entry point calls `init_tracing()` on startup so all agent pod executions are traced in Jaeger and Langfuse.

6. **Argo Grafana dashboard** -- Custom dashboard built for Argo v4 metrics (v4 uses different metric names than v3). Proper color scheme, workflow status panels, pod duration histograms.

## Files Created

```
infra/k8s/helm-values/argo-workflows.yaml              # Kind Helm values
infra/k8s/helm-values/argo-workflows-gke.yaml          # GKE Helm values
infra/k8s/argo-templates/agent-worker.yaml             # Parameterized WorkflowTemplate
infra/k8s/argo-templates/rbac.yaml                     # RBAC for null-realm-agents namespace
nullrealm/orchestrator/__init__.py
nullrealm/orchestrator/argo_client.py                  # Async Argo REST API client
infra/k8s/gke/argo-metrics.yaml                        # ServiceMonitor for Argo v4 metrics
infra/k8s/gke/grafana-dashboards/                      # Custom Argo v4 Grafana dashboard
```

## Files Modified

```
nullrealm/worker/bootstrap.py    # Added init_tracing() call on startup
nullrealm/worker/main.py         # Updated entry point for Argo pod execution
tasks.py                         # Added deploy_argo invoke task
```

## Deviations from Plan

1. **Removed S3 artifact repo from Helm values** -- Plan assumed S3 for artifact storage. Not needed on Kind; removed to simplify.
2. **Worker bootstrap missing init_tracing()** -- Initial implementation didn't call `init_tracing()`, so agent pod traces were invisible. Added after noticing missing traces in Langfuse.
3. **Argo v4 metrics use HTTPS** -- ServiceMonitor needed `tlsConfig.insecureSkipVerify: true` to scrape the metrics endpoint. v3 used plain HTTP.
4. **Argo server needed --managed-namespace** -- Added `--managed-namespace=null-realm-agents` flag for the Argo UI to display workflows in the correct namespace.
5. **Argo v4 has no dark mode** -- Only `navColor` customization available. Built custom dashboard with appropriate colors instead.
6. **Pre-built Grafana dashboards used v3 metric names** -- Argo v4 renamed metrics (e.g., `argo_workflows_count` -> `argo_workflows_gauge`). Built a custom v4 dashboard from scratch instead of adapting v3 dashboards.

## Verification Results

- [x] Argo server and workflow controller Running on Kind
- [x] Argo UI accessible at localhost:2746
- [x] Agent worker WorkflowTemplate submitted and pod executes
- [x] Worker pod traces appear in Jaeger and Langfuse
- [x] RBAC allows pod creation in null-realm-agents namespace
- [x] Argo deployed on GKE with UI at argo.34.53.165.155.nip.io
- [x] Grafana dashboard shows Argo v4 workflow metrics

## Next Step

**04-02**: Multiple assistants + workflow execution + Chainlit step visualization.
