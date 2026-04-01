"""VPC and subnet for GKE + Cloud SQL."""
import pulumi_gcp as gcp

LABELS = {"user": "anurag", "project": "null-realm"}


def create_network():
    network = gcp.compute.Network(
        "null-realm-vpc",
        name="null-realm-vpc",
        auto_create_subnetworks=False,
        project="helpful-rope-230010",
    )

    subnet = gcp.compute.Subnetwork(
        "null-realm-subnet",
        name="null-realm-subnet",
        ip_cidr_range="10.0.0.0/20",
        region="europe-west1",
        network=network.id,
        project="helpful-rope-230010",
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
        project="helpful-rope-230010",
        labels=LABELS,
    )

    private_vpc_connection = gcp.servicenetworking.Connection(
        "null-realm-vpc-connection",
        network=network.id,
        service="servicenetworking.googleapis.com",
        reserved_peering_ranges=[private_ip_alloc.name],
    )

    return network, subnet, private_vpc_connection
