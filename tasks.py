"""Invoke tasks for Null Realm local development.

Usage:
    invoke kind-up              # Create Kind cluster + namespaces
    invoke kind-down            # Delete Kind cluster
    invoke build                # Build all Docker images
    invoke load-images          # Load images into Kind
    invoke deploy-local         # Apply K8s manifests
    invoke deploy-observability # Deploy Prometheus + Grafana via Helm
    invoke dev                  # Full local dev cycle

    invoke pulumi-up            # Provision/update GCP infrastructure
    invoke pulumi-destroy       # Tear down all GCP infra (stops billing)
    invoke get-gke-credentials  # Get kubeconfig for GKE cluster

    invoke sql-stop             # Stop Cloud SQL to save costs (~$1.78/day)
    invoke sql-start            # Start Cloud SQL before a session
    invoke gcp-status           # Show all deployed GCP resources
"""

from invoke import task

CLUSTER_NAME = "null-realm"
KIND_CONFIG = "scripts/kind-config.yaml"
NAMESPACE_YAML = "infra/k8s/base/namespace.yaml"

IMAGES = {
    "null-realm-api": "Dockerfile.api",
    "null-realm-worker": "Dockerfile.worker",
    "null-realm-ui": "Dockerfile.ui",
}


@task
def kind_up(c):
    """Create Kind cluster and apply namespaces."""
    # Check if cluster already exists
    result = c.run(f"kind get clusters 2>/dev/null | grep -q '^{CLUSTER_NAME}$'", warn=True)
    if result.ok:
        print(f"Kind cluster '{CLUSTER_NAME}' already exists.")
    else:
        c.run(f"kind create cluster --config {KIND_CONFIG}")
        print(f"Kind cluster '{CLUSTER_NAME}' created.")

    # Apply namespaces
    c.run(f"kubectl apply -f {NAMESPACE_YAML}")
    print("Namespaces applied.")


@task
def kind_down(c):
    """Delete Kind cluster."""
    c.run(f"kind delete cluster --name {CLUSTER_NAME}")
    print(f"Kind cluster '{CLUSTER_NAME}' deleted.")


@task
def build(c, service="all"):
    """Build Docker images. Use --service=api|worker|ui to build one."""
    if service == "all":
        targets = IMAGES.items()
    else:
        key = f"null-realm-{service}"
        if key not in IMAGES:
            print(f"Unknown service: {service}. Choose from: api, worker, ui")
            return
        targets = [(key, IMAGES[key])]

    for image_name, dockerfile in targets:
        print(f"Building {image_name} from {dockerfile}...")
        c.run(f"docker build -t {image_name}:latest -f {dockerfile} .")
    print("Build complete.")


@task
def load_images(c):
    """Load all Docker images into Kind cluster."""
    for image_name in IMAGES:
        print(f"Loading {image_name} into Kind...")
        c.run(f"kind load docker-image {image_name}:latest --name {CLUSTER_NAME}")
    print("All images loaded into Kind.")


@task
def deploy_local(c):
    """Apply all K8s manifests to local Kind cluster."""
    c.run(f"kubectl apply -f {NAMESPACE_YAML}")
    # Future: apply deployment manifests here
    print("Local deploy complete. (Namespace manifests only for now)")


@task
def deploy_observability(c):
    """Deploy Prometheus + Grafana via Helm, Jaeger, Postgres, and Langfuse on the local Kind cluster."""
    c.run(
        "helm upgrade --install prometheus prometheus-community/kube-prometheus-stack"
        " -n null-realm"
        " -f infra/k8s/helm-values/prometheus-grafana.yaml"
        " --timeout 5m"
        " --wait"
    )
    print("Prometheus + Grafana deployed.")

    # Deploy Jaeger all-in-one (in-memory, dev-only)
    c.run("kubectl apply -f infra/k8s/system/jaeger/deployment.yaml")
    c.run("kubectl apply -f infra/k8s/system/jaeger/service.yaml")
    c.run("kubectl rollout status deployment/jaeger -n null-realm --timeout=2m")
    print("Jaeger deployed.")

    # Deploy shared PostgreSQL (used by Langfuse)
    c.run("kubectl apply -f infra/k8s/system/postgres/statefulset.yaml")
    c.run("kubectl apply -f infra/k8s/system/postgres/service.yaml")
    c.run("kubectl rollout status statefulset/postgres -n null-realm --timeout=3m")
    print("PostgreSQL deployed.")

    # Deploy Langfuse self-hosted (LLM observability + tracing)
    c.run("kubectl apply -f infra/k8s/system/langfuse/deployment.yaml")
    c.run("kubectl apply -f infra/k8s/system/langfuse/service.yaml")
    c.run("kubectl rollout status deployment/langfuse -n null-realm --timeout=5m")
    print("Langfuse deployed.")

    print("Observability stack deployed.")
    print("  Grafana:  http://localhost:3000  (admin / admin)")
    print("  Jaeger:   http://localhost:16686")
    print("  Langfuse: http://localhost:3001")


@task
def get_gke_credentials(c):
    """Get kubeconfig credentials for GKE cluster."""
    c.run(
        "gcloud container clusters get-credentials null-realm "
        "--region europe-west1 --project helpful-rope-230010"
    )


@task
def pulumi_up(c):
    """Provision/update GCP infrastructure via Pulumi."""
    with c.cd("infra/pulumi"):
        c.run("PULUMI_CONFIG_PASSPHRASE='' pulumi up --yes --stack dev")


@task
def pulumi_destroy(c):
    """Tear down all GCP infrastructure (stops billing)."""
    with c.cd("infra/pulumi"):
        c.run("PULUMI_CONFIG_PASSPHRASE='' pulumi destroy --yes --stack dev")


@task
def sql_stop(c):
    """Stop Cloud SQL instance to save ~$1.78/day. Storage still billed (~$0.58/day)."""
    c.run(
        "gcloud sql instances patch null-realm-db "
        "--activation-policy NEVER "
        "--project helpful-rope-230010"
    )
    print("Cloud SQL stopped. Run 'invoke sql-start' before your next session.")


@task
def sql_start(c):
    """Start Cloud SQL instance before a dev session."""
    c.run(
        "gcloud sql instances patch null-realm-db "
        "--activation-policy ALWAYS "
        "--project helpful-rope-230010"
    )
    print("Cloud SQL starting... (takes ~30 seconds to be ready)")


@task
def gcp_status(c):
    """Show all deployed null-realm GCP resources (labeled project:null-realm)."""
    project = "helpful-rope-230010"
    print("\n=== GKE Clusters ===")
    c.run(f"gcloud container clusters list --project={project} --format='table(name,location,status,currentMasterVersion)'", warn=True)

    print("\n=== Cloud SQL Instances ===")
    c.run(f"gcloud sql instances list --project={project} --format='table(name,region,databaseVersion,state)'", warn=True)

    print("\n=== Artifact Registry ===")
    c.run(f"gcloud artifacts repositories list --project={project} --format='table(name,format,location)'", warn=True)

    print("\n=== Secret Manager (null-realm) ===")
    c.run(f"gcloud secrets list --project={project} --filter='labels.project=null-realm' --format='table(name,createTime)'", warn=True)

    print("\n=== Pulumi Stack Outputs ===")
    c.run("bash -c 'cd infra/pulumi && PULUMI_CONFIG_PASSPHRASE=\"\" pulumi stack output 2>/dev/null'", warn=True)


@task(pre=[kind_up])
def dev(c):
    """Full local dev cycle: kind-up, build, load-images, deploy."""
    build(c)
    load_images(c)
    deploy_local(c)
    print("\nLocal dev environment ready!")
    print("  API:     http://localhost:8000")
    print("  UI:      http://localhost:8501")
    print("  Grafana: http://localhost:3000")
    print("  Jaeger:  http://localhost:16686")
    print("  Langfuse:http://localhost:3001")
