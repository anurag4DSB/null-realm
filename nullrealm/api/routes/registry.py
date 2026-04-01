"""Registry CRUD routes for tools, prompts, assistants, and workflows."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nullrealm.registry.database import get_db
from nullrealm.registry.models import Assistant, Prompt, Tool, Workflow
from nullrealm.registry.schemas import (
    AssistantCreate,
    AssistantRead,
    AssistantUpdate,
    PromptCreate,
    PromptRead,
    PromptUpdate,
    ToolCreate,
    ToolRead,
    ToolUpdate,
    WorkflowCreate,
    WorkflowRead,
    WorkflowUpdate,
)

router = APIRouter(prefix="/api/v1/registry", tags=["registry"])


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@router.get("/tools", response_model=list[ToolRead])
async def list_tools(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tool).order_by(Tool.name))
    return result.scalars().all()


@router.post("/tools", response_model=ToolRead, status_code=201)
async def create_tool(body: ToolCreate, db: AsyncSession = Depends(get_db)):
    tool = Tool(**body.model_dump())
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("/tools/{name}", response_model=ToolRead)
async def get_tool(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tool).where(Tool.name == name))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    return tool


@router.put("/tools/{name}", response_model=ToolRead)
async def update_tool(name: str, body: ToolUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tool).where(Tool.name == name))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(tool, key, value)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.delete("/tools/{name}", status_code=204)
async def delete_tool(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tool).where(Tool.name == name))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    await db.delete(tool)
    await db.commit()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@router.get("/prompts", response_model=list[PromptRead])
async def list_prompts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).order_by(Prompt.name))
    return result.scalars().all()


@router.post("/prompts", response_model=PromptRead, status_code=201)
async def create_prompt(body: PromptCreate, db: AsyncSession = Depends(get_db)):
    prompt = Prompt(**body.model_dump())
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return prompt


@router.get("/prompts/{name}", response_model=PromptRead)
async def get_prompt(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).where(Prompt.name == name))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
    return prompt


@router.put("/prompts/{name}", response_model=PromptRead)
async def update_prompt(name: str, body: PromptUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).where(Prompt.name == name))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(prompt, key, value)
    await db.commit()
    await db.refresh(prompt)
    return prompt


@router.delete("/prompts/{name}", status_code=204)
async def delete_prompt(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).where(Prompt.name == name))
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
    await db.delete(prompt)
    await db.commit()


# ---------------------------------------------------------------------------
# Assistants
# ---------------------------------------------------------------------------


@router.get("/assistants", response_model=list[AssistantRead])
async def list_assistants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Assistant).order_by(Assistant.name))
    return result.scalars().all()


@router.post("/assistants", response_model=AssistantRead, status_code=201)
async def create_assistant(body: AssistantCreate, db: AsyncSession = Depends(get_db)):
    assistant = Assistant(**body.model_dump())
    db.add(assistant)
    await db.commit()
    await db.refresh(assistant)
    return assistant


@router.get("/assistants/{name}", response_model=AssistantRead)
async def get_assistant(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Assistant).where(Assistant.name == name))
    assistant = result.scalar_one_or_none()
    if assistant is None:
        raise HTTPException(status_code=404, detail=f"Assistant '{name}' not found")
    return assistant


@router.put("/assistants/{name}", response_model=AssistantRead)
async def update_assistant(name: str, body: AssistantUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Assistant).where(Assistant.name == name))
    assistant = result.scalar_one_or_none()
    if assistant is None:
        raise HTTPException(status_code=404, detail=f"Assistant '{name}' not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(assistant, key, value)
    await db.commit()
    await db.refresh(assistant)
    return assistant


@router.delete("/assistants/{name}", status_code=204)
async def delete_assistant(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Assistant).where(Assistant.name == name))
    assistant = result.scalar_one_or_none()
    if assistant is None:
        raise HTTPException(status_code=404, detail=f"Assistant '{name}' not found")
    await db.delete(assistant)
    await db.commit()


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


@router.get("/workflows", response_model=list[WorkflowRead])
async def list_workflows(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).order_by(Workflow.name))
    return result.scalars().all()


@router.post("/workflows", response_model=WorkflowRead, status_code=201)
async def create_workflow(body: WorkflowCreate, db: AsyncSession = Depends(get_db)):
    workflow = Workflow(**body.model_dump())
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)
    return workflow


@router.get("/workflows/{name}", response_model=WorkflowRead)
async def get_workflow(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.name == name))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    return workflow


@router.put("/workflows/{name}", response_model=WorkflowRead)
async def update_workflow(name: str, body: WorkflowUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.name == name))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(workflow, key, value)
    await db.commit()
    await db.refresh(workflow)
    return workflow


@router.delete("/workflows/{name}", status_code=204)
async def delete_workflow(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.name == name))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    await db.delete(workflow)
    await db.commit()
