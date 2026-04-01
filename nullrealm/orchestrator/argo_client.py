"""Argo Workflows client for submitting and monitoring agent workflows."""

import os

import httpx


class ArgoClient:
    def __init__(self):
        self.base_url = os.getenv(
            "ARGO_SERVER_URL",
            "http://argo-workflows-server.null-realm.svc.cluster.local:2746",
        )

    async def submit_workflow(self, template_name: str, params: dict) -> str:
        """Submit a workflow from a WorkflowTemplate."""
        body = {
            "resourceKind": "WorkflowTemplate",
            "resourceName": template_name,
            "submitOptions": {
                "parameters": [f"{k}={v}" for k, v in params.items()]
            },
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/workflows/null-realm-agents/submit",
                json=body,
            )
            resp.raise_for_status()
            return resp.json()["metadata"]["name"]

    async def get_workflow_status(self, workflow_name: str) -> dict:
        """Get the status of a workflow by name."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/workflows/null-realm-agents/{workflow_name}"
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "name": data["metadata"]["name"],
                "phase": data["status"].get("phase", "Unknown"),
                "started": data["status"].get("startedAt"),
                "finished": data["status"].get("finishedAt"),
            }
