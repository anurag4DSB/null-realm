"""Cloud Build trigger for CI/CD."""
import pulumi_gcp as gcp


def create_cloudbuild_trigger(github_owner: str, github_repo: str, sa_cloudbuild):
    """Create a Cloud Build trigger that fires on push to main."""
    trigger = gcp.cloudbuild.Trigger(
        "null-realm-main-trigger",
        project="helpful-rope-230010",
        name="null-realm-push-to-main",
        description="Build and deploy on push to main",
        github=gcp.cloudbuild.TriggerGithubArgs(
            owner=github_owner,
            name=github_repo,
            push=gcp.cloudbuild.TriggerGithubPushArgs(
                branch="^main$",
            ),
        ),
        filename="cloudbuild.yaml",
        service_account=sa_cloudbuild.id,
    )
    return trigger
