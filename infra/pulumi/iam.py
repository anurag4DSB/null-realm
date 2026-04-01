"""Service accounts for GKE workloads and Cloud Build."""
import pulumi_gcp as gcp


def create_service_accounts(artifact_registry):
    # GKE workload service account
    sa_gke = gcp.serviceaccount.Account(
        "null-realm-gke-sa",
        account_id="null-realm-gke",
        display_name="Null Realm GKE Workload SA",
        project="helpful-rope-230010",
    )

    # Allow GKE SA to pull from Artifact Registry
    gcp.artifactregistry.RepositoryIamMember(
        "gke-sa-ar-reader",
        project="helpful-rope-230010",
        location="europe-west1",
        repository=artifact_registry.repository_id,
        role="roles/artifactregistry.reader",
        member=sa_gke.email.apply(lambda e: f"serviceAccount:{e}"),
    )

    # Cloud Build service account
    sa_cloudbuild = gcp.serviceaccount.Account(
        "null-realm-cloudbuild-sa",
        account_id="null-realm-cloudbuild",
        display_name="Null Realm Cloud Build SA",
        project="helpful-rope-230010",
    )

    # Cloud Build SA permissions
    project_id = "helpful-rope-230010"
    for role in [
        "roles/container.developer",
        "roles/artifactregistry.writer",
        "roles/storage.admin",
    ]:
        gcp.projects.IAMMember(
            f"cloudbuild-sa-{role.split('/')[-1]}",
            project=project_id,
            role=role,
            member=sa_cloudbuild.email.apply(lambda e: f"serviceAccount:{e}"),
        )

    return sa_gke, sa_cloudbuild
