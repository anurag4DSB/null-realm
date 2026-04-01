"""Workflow execution routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nullrealm.orchestrator.workflow_executor import WorkflowExecutor
from nullrealm.registry.database import get_db
from nullrealm.registry.models import Workflow

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


class WorkflowExecuteRequest(BaseModel):
    input: str
    session_id: str = "default"


class WorkflowExecuteResponse(BaseModel):
    workflow_name: str
    steps: dict


@router.post("/{name}/execute")
async def execute_workflow(
    name: str,
    req: WorkflowExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workflow).where(Workflow.name == name))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(404, f"Workflow '{name}' not found")

    executor = WorkflowExecutor()
    config = {
        "name": workflow.name,
        "steps": workflow.steps,
        "max_parallel_agents": workflow.max_parallel_agents,
    }
    results = await executor.execute_workflow(config, req.input, req.session_id)

    return WorkflowExecuteResponse(workflow_name=name, steps=results)
