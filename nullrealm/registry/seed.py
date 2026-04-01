"""Seed the registry database from agent_configs/ YAML and Markdown files.

Usage:
    uv run python -m nullrealm.registry.seed
"""

import asyncio
import logging
import re
from pathlib import Path

import yaml
from sqlalchemy import select

from nullrealm.registry.database import async_session, init_db
from nullrealm.registry.models import Assistant, Prompt, Tool, Workflow

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Resolve the repo root — works whether run from repo root or from inside the package
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
CONFIGS_DIR = _REPO_ROOT / "agent_configs"


async def _upsert_tools() -> int:
    """Load tool YAML files and insert any that don't already exist."""
    tools_dir = CONFIGS_DIR / "tools"
    if not tools_dir.exists():
        logger.warning("No tools directory at %s", tools_dir)
        return 0

    count = 0
    async with async_session() as db:
        for path in sorted(tools_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            name = data["name"]
            result = await db.execute(select(Tool).where(Tool.name == name))
            if result.scalar_one_or_none() is not None:
                logger.info("Tool '%s' already exists — skipping", name)
                continue
            tool = Tool(
                name=name,
                version=data.get("version", "1.0"),
                description=data.get("description", ""),
                input_schema=data.get("input_schema", {}),
                execution_type=data.get("execution_type", "python"),
                execution_config=data.get("execution_config", {}),
            )
            db.add(tool)
            count += 1
            logger.info("Inserted tool '%s'", name)
        await db.commit()
    return count


async def _upsert_prompts() -> int:
    """Load prompt Markdown files and insert any that don't already exist."""
    prompts_dir = CONFIGS_DIR / "prompts"
    if not prompts_dir.exists():
        logger.warning("No prompts directory at %s", prompts_dir)
        return 0

    count = 0
    async with async_session() as db:
        for path in sorted(prompts_dir.glob("*.md")):
            name = path.stem  # e.g. research_agent
            template = path.read_text().strip()
            # Extract Jinja2 variable names from {{ var }}
            variables = sorted(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", template)))

            result = await db.execute(select(Prompt).where(Prompt.name == name))
            if result.scalar_one_or_none() is not None:
                logger.info("Prompt '%s' already exists — skipping", name)
                continue

            prompt = Prompt(
                name=name,
                version="1.0",
                template=template,
                variables=variables,
                model_hint=None,
            )
            db.add(prompt)
            count += 1
            logger.info("Inserted prompt '%s'", name)
        await db.commit()
    return count


async def _upsert_assistants() -> int:
    """Load assistant YAML files and insert any that don't already exist."""
    assistants_dir = CONFIGS_DIR / "assistants"
    if not assistants_dir.exists():
        logger.warning("No assistants directory at %s", assistants_dir)
        return 0

    count = 0
    async with async_session() as db:
        for path in sorted(assistants_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            name = data["name"]
            result = await db.execute(select(Assistant).where(Assistant.name == name))
            if result.scalar_one_or_none() is not None:
                logger.info("Assistant '%s' already exists — skipping", name)
                continue
            assistant = Assistant(
                name=name,
                prompt_name=data.get("prompt_name", ""),
                model_preference=data.get("model_preference", "claude-sonnet"),
                tool_allowlist=data.get("tool_allowlist", []),
                system_prompt=data.get("system_prompt", ""),
            )
            db.add(assistant)
            count += 1
            logger.info("Inserted assistant '%s'", name)
        await db.commit()
    return count


async def _upsert_workflows() -> int:
    """Load workflow YAML files and insert any that don't already exist."""
    workflows_dir = CONFIGS_DIR / "workflows"
    if not workflows_dir.exists():
        logger.warning("No workflows directory at %s", workflows_dir)
        return 0

    count = 0
    async with async_session() as db:
        for path in sorted(workflows_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            name = data["name"]
            result = await db.execute(select(Workflow).where(Workflow.name == name))
            if result.scalar_one_or_none() is not None:
                logger.info("Workflow '%s' already exists — skipping", name)
                continue
            workflow = Workflow(
                name=name,
                steps=data.get("steps", []),
                max_parallel_agents=data.get("max_parallel_agents", 1),
            )
            db.add(workflow)
            count += 1
            logger.info("Inserted workflow '%s'", name)
        await db.commit()
    return count


async def seed():
    """Run all seed operations."""
    await init_db()
    tools = await _upsert_tools()
    prompts = await _upsert_prompts()
    assistants = await _upsert_assistants()
    workflows = await _upsert_workflows()
    logger.info(
        "Seed complete — %d tools, %d prompts, %d assistants, %d workflows inserted",
        tools,
        prompts,
        assistants,
        workflows,
    )


if __name__ == "__main__":
    asyncio.run(seed())
