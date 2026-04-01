---
phase: 03-streaming-persistence
plan: 03-02
status: complete
completed: 2026-04-01
---

# Summary: 03-02 PostgreSQL Registry Tables + CRUD API + Seed Data

## What Was Accomplished

1. **SQLAlchemy 2.0 models** -- Four registry tables: `Tool`, `Prompt`, `Assistant`, `Workflow`. Async engine and session factory using asyncpg. pgvector extension enabled.

2. **Full CRUD API** -- RESTful endpoints at `/api/v1/registry/{tools,prompts,assistants,workflows}` with GET (list/detail), POST, PUT, DELETE operations. Mounted in FastAPI app.

3. **Seed data from agent_configs/** -- 5 tools (file_read, bash, web_search, grep, code_search), 2 prompts (research_agent, poc_writer), 1 assistant (research) loaded from YAML and Markdown files.

4. **DATABASE_URL wired to api-server** -- API server deployment updated with DATABASE_URL environment variable pointing to PostgreSQL service.

## Files Created

```
nullrealm/registry/__init__.py
nullrealm/registry/models.py              # SQLAlchemy 2.0 models (Tool, Prompt, Assistant, Workflow)
nullrealm/registry/schemas.py             # Pydantic request/response schemas
nullrealm/registry/database.py            # Async engine + session factory (asyncpg)
nullrealm/registry/seed.py                # Load YAML/MD configs into DB
nullrealm/api/routes/registry.py          # CRUD endpoints for all 4 registries
agent_configs/tools/file_read.yaml
agent_configs/tools/bash.yaml
agent_configs/tools/web_search.yaml
agent_configs/tools/grep.yaml
agent_configs/tools/code_search.yaml
agent_configs/prompts/research_agent.md
agent_configs/prompts/poc_writer.md
agent_configs/assistants/research.yaml
```

## Files Modified

```
nullrealm/main.py                                    # Mount registry router, DB init in lifespan
nullrealm/config.py                                  # Added DATABASE_URL setting
pyproject.toml                                       # Added sqlalchemy, asyncpg, pgvector
infra/k8s/system/api-server/deployment.yaml          # Added DATABASE_URL env var
```

## Deviations from Plan

1. **Skipped Alembic migrations** -- Plan called for Alembic. Used `create_all()` instead for simplicity at this stage. Schema changes require manual table drop/recreate.
2. **Had to drop/recreate tables on GKE** -- Schema mismatch between local and GKE required manual table cleanup due to lack of Alembic migrations.
3. **No Session/Message/Evaluation tables** -- Plan included chat persistence tables and Phase 06 evaluation table. Deferred to keep scope focused on the 4 registry tables.
4. **PostgreSQL 16 sufficient** -- No need to upgrade; pgvector extension works fine on existing PG 16 instance.
5. **No prompt render endpoint** -- Plan included `POST /api/v1/registry/prompts/{name}/render` for Jinja2 rendering. Deferred to Phase 04 when prompts are actually rendered during workflow execution.

## Verification Results

- [x] All 4 registry tables created in PostgreSQL
- [x] pgvector extension enabled
- [x] GET /api/v1/registry/tools returns 5 seeded tools
- [x] GET /api/v1/registry/prompts returns 2 prompts
- [x] GET /api/v1/registry/assistants returns 1 assistant
- [x] CRUD operations work (create, read, update, delete)
- [x] Seed script idempotent (can run multiple times)

## Next Step

**Phase 04**: Multi-Agent Workflows -- Argo Workflows deployment + agent worker pods.
