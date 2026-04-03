---
phase: 05-context-engineering
plan: 05-03
status: complete
completed: 2026-04-03
---

# Summary: 05-03 Multi-User Repo Management with Argo-Based Indexing

## What Was Accomplished

1. **Repository model + repos table** -- SQLAlchemy `Repository` model added to `nullrealm/registry/models.py`. Tracks name, URL, branch, auth_type (public/token), status (pending/indexing/ready/failed), chunk_count, file_count, last_indexed_at, index_error. Auto-created via `Base.metadata.create_all` in `init_db()`.

2. **Argo repo-indexer WorkflowTemplate** -- `infra/k8s/argo-templates/repo-indexer.yaml` (Kind) and `infra/k8s/gke/argo-templates/repo-indexer.yaml` (GKE). Runs indexing in dedicated pods with git, embedding, and Neo4j access. Params: url, branch, repo_name, auth_type. GITHUB_TOKEN mounted from mcp-secrets (optional).

3. **CLI entrypoint for Argo pods** -- `nullrealm/context/repo_manager_cli.py` parses args, updates repos table status to "indexing", calls `index_repository()`, then updates to "ready" (or "failed" with error message).

4. **repo_manager.py rewrite** -- Added async DB helpers (`_get_engine()`, `_get_session_factory()`), `register_repo()`, `update_repo_status()`, `get_repo()`. Updated `clone_or_pull()` with PAT auth support (rewrites HTTPS URL with GITHUB_TOKEN). Updated `list_indexed_repos()` to query repos table. Updated `delete_repository_index()` to use Neo4j `delete_by_repo()` and clean repos table.

5. **MCP tools updated** -- `index_repo` now submits Argo workflow (non-blocking), `list_repos` shows rich status from repos table, new `add_repo` tool registers without indexing. MCP server calls `init_db()` on startup to ensure repos table exists.

6. **Neo4j repo property** -- Symbol nodes now have a `repo` property. New index on `repo` for fast lookups. `delete_by_repo()` method for clean per-repo deletion (replaces fragile file-prefix matching).

7. **Worker image updated** -- `Dockerfile.worker` now installs `git` and `openssh-client`. MCP image stays lightweight (no git).

8. **Deployed and verified on Kind and GKE** -- Cloudserver indexed successfully via Argo workflow on both environments. 21 chunks, 5 files (Python files only — JS support coming in 05-04).

## Key Stats

- 9 MCP tools (was 8): added `add_repo`
- Argo repo-indexer template: 2Gi memory (Kind), 1Gi (GKE — uses Vertex AI embeddings, no sentence-transformers fallback)
- Cloudserver indexing: ~1 min on GKE (Vertex AI), ~2 min on Kind (sentence-transformers fallback)
- repos table: status tracking, error messages, chunk/file counts, last_indexed_at

## Files Created

```
nullrealm/context/repo_manager_cli.py              # Argo pod CLI entrypoint
infra/k8s/argo-templates/repo-indexer.yaml          # Kind WorkflowTemplate
infra/k8s/gke/argo-templates/repo-indexer.yaml      # GKE WorkflowTemplate
```

## Files Modified

```
nullrealm/registry/models.py                        # Added Repository model
nullrealm/context/repo_manager.py                   # repos table CRUD, PAT auth, async DB
nullrealm/context/neo4j_store.py                    # repo property, delete_by_repo()
nullrealm/context/indexer.py                        # Pass repo_name through to store_graph
nullrealm/mcp_server.py                             # Argo workflow submission, add_repo tool, init_db()
Dockerfile.worker                                   # Added git + openssh-client
```

## Deviations from Plan

1. **Worker memory bumped to 2Gi on Kind** -- sentence-transformers fallback (used when LiteLLM embedding fails) loads all-mpnet-base-v2 model (~420MB) which OOMs at 1Gi. GKE stays at 1Gi since Vertex AI embeddings via LiteLLM work there.
2. **MCP server gets `init_db()` on startup** -- Added to lifespan so repos table is created even if API server hasn't started. Not in original plan but needed for standalone MCP operation.
3. **Cloudserver branch is `development/9.2`** -- First attempt with `main` branch failed (doesn't exist). Documented for future reference.

## Verification Results

- [x] repos table exists with correct schema (Kind + GKE)
- [x] Argo repo-indexer template created and applied (Kind + GKE)
- [x] Worker image has git installed
- [x] index_repo triggers Argo workflow (async, returns immediately)
- [x] list_repos shows status from repos table
- [x] delete_repo_index cleans all stores + repos table
- [x] Public repo (cloudserver) indexes successfully
- [ ] Private repo indexes with GITHUB_TOKEN (secret created, untested — user has PAT ready)
- [x] Neo4j nodes have repo property
- [x] Status tracking works (pending → indexing → ready, or → failed with error)

## Next Step

**Phase 05-04**: Multi-language indexing (JS/TS/Go) via tree-sitter — cloudserver's core JS code is currently unindexed.
