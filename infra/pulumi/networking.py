"""VPC and subnet for GKE + Cloud SQL."""
import pulumi_gcp as gcp
from gcp_project import GCP_PROJECT

LABELS = {"user": "anurag", "project": "null-realm"}


def create_network():
    network = gcp.compute.Network(
        "null-realm-vpc",
        name="null-realm-vpc",
        auto_create_subnetworks=False,
        project=GCP_PROJECT,
    )

    subnet = gcp.compute.Subnetwork(
        "null-realm-subnet",
        name="null-realm-subnet",
        ip_cidr_range="10.0.0.0/20",
        region="europe-west1",
        network=network.id,
        project=GCP_PROJECT,
        secondary_ip_ranges=[
            gcp.compute.SubnetworkSecondaryIpRangeArgs(
                range_name="pods",
                ip_cidr_range="10.100.0.0/16",
            ),
            gcp.compute.SubnetworkSecondaryIpRangeArgs(
                range_name="services",
                ip_cidr_range="10.101.0.0/20",
            ),
        ],
    )

    # Private services access for Cloud SQL
    private_ip_alloc = gcp.compute.GlobalAddress(
        "null-realm-private-ip",
        name="null-realm-private-ip",
        purpose="VPC_PEERING",
        address_type="INTERNAL",
        prefix_length=16,
        network=network.id,
        project=GCP_PROJECT,
        labels=LABELS,
    )

    private_vpc_connection = gcp.servicenetworking.Connection(
        "null-realm-vpc-connection",
        network=network.id,
        service="servicenetworking.googleapis.com",
        reserved_peering_ranges=[private_ip_alloc.name],
    )

    # Cloud NAT — required for private GKE nodes to pull external images
    router = gcp.compute.Router(
        "null-realm-router",
        name="null-realm-router",
        network=network.id,
        region="europe-west1",
        project=GCP_PROJECT,
    )

    gcp.compute.RouterNat(
        "null-realm-nat",
        name="null-realm-nat",
        router=router.name,
        region="europe-west1",
        project=GCP_PROJECT,
        nat_ip_allocate_option="AUTO_ONLY",
        source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
        log_config=gcp.compute.RouterNatLogConfigArgs(
            enable=True,
            filter="ERRORS_ONLY",
        ),
    )

    return network, subnet, private_vpc_connection
