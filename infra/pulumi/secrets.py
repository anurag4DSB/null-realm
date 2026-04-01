"""Secret Manager secrets for API keys and credentials."""
import pulumi_gcp as gcp

LABELS = {"user": "anurag", "project": "null-realm"}


def create_secrets():
    project = "helpful-rope-230010"
    replication = gcp.secretmanager.SecretReplicationArgs(
        auto=gcp.secretmanager.SecretReplicationAutoArgs(),
    )

    secrets = {}

    secrets["anthropic_api_key"] = gcp.secretmanager.Secret(
        "anthropic-api-key",
        secret_id="ANTHROPIC_API_KEY",
        project=project,
        replication=replication,
        labels=LABELS,
    )

    secrets["database_url"] = gcp.secretmanager.Secret(
        "database-url",
        secret_id="DATABASE_URL",
        project=project,
        replication=replication,
        labels=LABELS,
    )

    secrets["oauth2_client_id"] = gcp.secretmanager.Secret(
        "oauth2-client-id",
        secret_id="OAUTH2_CLIENT_ID",
        project=project,
        replication=replication,
        labels=LABELS,
    )

    secrets["oauth2_client_secret"] = gcp.secretmanager.Secret(
        "oauth2-client-secret",
        secret_id="OAUTH2_CLIENT_SECRET",
        project=project,
        replication=replication,
        labels=LABELS,
    )

    secrets["oauth2_cookie_secret"] = gcp.secretmanager.Secret(
        "oauth2-cookie-secret",
        secret_id="OAUTH2_COOKIE_SECRET",
        project=project,
        replication=replication,
        labels=LABELS,
    )

    return secrets
