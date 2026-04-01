"""Execute multi-step workflows via Argo."""

import asyncio
import logging
import os

from nullrealm.orchestrator.argo_client import ArgoClient

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    def __init__(self):
        self.argo = ArgoClient()

    async def execute_workflow(self, workflow_config: dict, user_input: str, session_id: str) -> dict:
        """Execute a workflow by submitting Argo steps sequentially."""
        steps = workflow_config.get("steps", [])
        workflow_name = workflow_config.get("name", "unknown")

        logger.info("Starting workflow '%s' with %d steps", workflow_name, len(steps))

        context = user_input
        results = {}

        for i, step in enumerate(steps):
            step_name = step["name"]
            assistant = step["assistant"]

            # Build task input: original input + previous step results
            if i == 0:
                task_input = user_input
            else:
                task_input = f"Original request: {user_input}\n\nPrevious step results:\n{context}"

            msg_id = f"{session_id}-step-{i}-{step_name}"

            logger.info(
                "Submitting step %d/%d: %s (assistant: %s)",
                i + 1, len(steps), step_name, assistant,
            )

            try:
                workflow_id = await self.argo.submit_workflow(
                    template_name="agent-worker",
                    params={
                        "assistant_name": assistant,
                        "session_id": session_id,
                        "task_input": task_input,
                        "msg_id": msg_id,
                    },
                )

                # Wait for completion
                status = {"phase": "Unknown"}
                for _ in range(120):  # 2 min timeout
                    status = await self.argo.get_workflow_status(workflow_id)
                    if status["phase"] in ("Succeeded", "Failed", "Error"):
                        break
                    await asyncio.sleep(1)

                if status["phase"] != "Succeeded":
                    logger.error("Step %s failed: %s", step_name, status["phase"])
                    context = f"[Step {step_name} failed]"
                else:
                    # Get the result from NATS or from the workflow logs
                    # For now, use the task_input as context chain
                    context = f"Step '{step_name}' completed successfully."

                results[step_name] = {"status": status["phase"], "workflow_id": workflow_id}

            except Exception:
                logger.exception("Failed to submit step %s", step_name)
                results[step_name] = {"status": "Error", "error": "submission failed"}

        return results
