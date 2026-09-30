"""GCP project ID, read from Pulumi config (``gcp:project``)."""
import pulumi

GCP_PROJECT = pulumi.Config("gcp").get("project") or "YOUR_GCP_PROJECT"
