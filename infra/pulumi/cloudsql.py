"""Cloud SQL PostgreSQL 16 with pgvector."""
import pulumi
import pulumi_gcp as gcp

LABELS = {"user": "anurag", "project": "null-realm"}


def create_cloud_sql(network, vpc_connection):
    db_instance = gcp.sql.DatabaseInstance(
        "null-realm-db",
        name="null-realm-db",
        database_version="POSTGRES_16",
        region="europe-west1",
        project="helpful-rope-230010",
        settings=gcp.sql.DatabaseInstanceSettingsArgs(
            tier="db-g1-small",
            disk_size=100,
            disk_type="PD_SSD",
            user_labels=LABELS,
            backup_configuration=gcp.sql.DatabaseInstanceSettingsBackupConfigurationArgs(
                enabled=True,
            ),
            ip_configuration=gcp.sql.DatabaseInstanceSettingsIpConfigurationArgs(
                ipv4_enabled=False,
                private_network=network.id,
                enable_private_path_for_google_cloud_services=True,
            ),
            # pgvector is a built-in extension in Cloud SQL PostgreSQL 15+.
            # Enable via: CREATE EXTENSION IF NOT EXISTS vector;
            # No database flag needed.
        ),
        deletion_protection=False,
        opts=pulumi.ResourceOptions(depends_on=[vpc_connection]),
    )

    # Create the database
    database = gcp.sql.Database(
        "null-realm-database",
        name="nullrealm",
        instance=db_instance.name,
        project="helpful-rope-230010",
    )

    # Create the user
    db_user = gcp.sql.User(
        "null-realm-db-user",
        name="nullrealm",
        instance=db_instance.name,
        password="nullrealm_gke_dev",
        project="helpful-rope-230010",
    )

    return db_instance
