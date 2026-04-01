"""GKE Autopilot cluster."""
import pulumi_gcp as gcp

LABELS = {"user": "anurag", "project": "null-realm"}


def create_gke_cluster(network, subnet, sa_gke):
    cluster = gcp.container.Cluster(
        "null-realm-gke",
        name="null-realm",
        location="europe-west1",
        project="helpful-rope-230010",
        enable_autopilot=True,
        network=network.name,
        subnetwork=subnet.name,
        resource_labels=LABELS,
        ip_allocation_policy=gcp.container.ClusterIpAllocationPolicyArgs(
            cluster_secondary_range_name="pods",
            services_secondary_range_name="services",
        ),
        private_cluster_config=gcp.container.ClusterPrivateClusterConfigArgs(
            enable_private_nodes=True,
            enable_private_endpoint=False,
            master_ipv4_cidr_block="172.16.0.0/28",
        ),
        release_channel=gcp.container.ClusterReleaseChannelArgs(
            channel="REGULAR",
        ),
        deletion_protection=False,
    )

    return cluster
