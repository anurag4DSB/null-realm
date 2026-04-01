"""Null Realm — GCP infrastructure via Pulumi Python."""
import pulumi
from networking import create_network
from registry import create_artifact_registry
from iam import create_service_accounts
from secrets import create_secrets
from gke import create_gke_cluster
from cloudsql import create_cloud_sql
from cloudbuild import create_cloudbuild_trigger

# Networking (VPC + subnets + private services connection) — must come first
network, subnet, vpc_connection = create_network()

# Artifact Registry — independent
artifact_registry = create_artifact_registry()

# Service accounts — independent
sa_gke, sa_cloudbuild = create_service_accounts(artifact_registry)

# Secrets — independent
secrets = create_secrets()

# GKE cluster — depends on network
gke_cluster = create_gke_cluster(network, subnet, sa_gke)

# Cloud SQL — depends on network and VPC peering connection
db_instance = create_cloud_sql(network, vpc_connection)

# Cloud Build trigger — fires on push to main.
# Requires GitHub App to be connected first via GCP Console:
#   https://console.cloud.google.com/cloud-build/triggers/connect?project=helpful-rope-230010
# Once connected, set config: pulumi config set github_connected true
# then re-run: pulumi up
config = pulumi.Config()
github_connected = config.get_bool("github_connected") or False

if github_connected:
    cloudbuild_trigger = create_cloudbuild_trigger(
        github_owner="anurag4DSB",
        github_repo="null-realm",
        sa_cloudbuild=sa_cloudbuild,
    )
    pulumi.export("cloudbuild_trigger_id", cloudbuild_trigger.trigger_id)
else:
    pulumi.log.info(
        "Skipping Cloud Build trigger — GitHub not yet connected. "
        "Connect at https://console.cloud.google.com/cloud-build/triggers/connect?project=helpful-rope-230010 "
        "then run: pulumi config set github_connected true && pulumi up"
    )

# Exports
pulumi.export("gke_cluster_name", gke_cluster.name)
pulumi.export("gke_endpoint", gke_cluster.endpoint)
pulumi.export("artifact_registry_url", artifact_registry.location.apply(
    lambda loc: f"{loc}-docker.pkg.dev/helpful-rope-230010/null-realm"
))
pulumi.export("db_instance_name", db_instance.name)
pulumi.export("db_connection_name", db_instance.connection_name)
