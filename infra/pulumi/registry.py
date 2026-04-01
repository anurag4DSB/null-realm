"""Artifact Registry for Docker images."""
import pulumi_gcp as gcp

LABELS = {"user": "anurag", "project": "null-realm"}


def create_artifact_registry():
    registry = gcp.artifactregistry.Repository(
        "null-realm-registry",
        repository_id="null-realm",
        format="DOCKER",
        location="europe-west1",
        project="YOUR_GCP_PROJECT",
        description="Null Realm Docker images",
        labels=LABELS,
    )
    return registry
