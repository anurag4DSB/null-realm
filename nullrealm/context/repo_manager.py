"""Repository management: clone, index, delete, list.

Manages the repos table for metadata tracking and provides functions
for cloning (with PAT auth), indexing, and lifecycle management.
"""

import asyncio
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

CACHE_DIR = os.getenv("REPO_CACHE_DIR", "/tmp/null-realm-repos")

# ---------------------------------------------------------------------------
# Async DB helpers (re-use the registry engine when possible, but also work
# standalone in Argo pods where the API server isn't running).
# ---------------------------------------------------------------------------

_engine = None


def _get_engine():
    """Return a cached async engine."""
    global _engine
    if _engine is None:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:5432/nullrealm",
        )
        _engine = create_async_engine(database_url, echo=False)
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_get_engine(), class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Repo table helpers
# ---------------------------------------------------------------------------


async def register_repo(
    name: str,
    url: str,
    branch: str = "main",
    auth_type: str = "public",
) -> dict:
    """Create or update a row in the repos table. Returns the repo as a dict."""
    from nullrealm.registry.models import Repository

    session_factory = _get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Repository).where(Repository.name == name)
            )
            repo = result.scalar_one_or_none()
            if repo is None:
                repo = Repository(
                    name=name,
                    url=url,
                    branch=branch,
                    auth_type=auth_type,
                    status="pending",
                )
                session.add(repo)
            else:
                repo.url = url
                repo.branch = branch
                repo.auth_type = auth_type
                repo.status = "pending"
                repo.index_error = None

        # Refresh to get server defaults
        await session.refresh(repo)
        return _repo_to_dict(repo)


async def update_repo_status(
    name: str,
    status: str,
    chunk_count: int | None = None,
    file_count: int | None = None,
    error: str | None = None,
    dep_map: dict | None = None,
) -> None:
    """Update the status (and optional stats) for a repo in the repos table."""
    from nullrealm.registry.models import Repository

    session_factory = _get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Repository).where(Repository.name == name)
            )
            repo = result.scalar_one_or_none()
            if repo is None:
                logger.warning("update_repo_status: repo '%s' not found", name)
                return
            repo.status = status
            if chunk_count is not None:
                repo.chunk_count = chunk_count
            if file_count is not None:
                repo.file_count = file_count
            if error is not None:
                repo.index_error = error
            if dep_map is not None:
                repo.dep_map = dep_map
            if status == "ready":
                repo.last_indexed_at = datetime.now(timezone.utc)
                repo.index_error = None


async def get_repo(name: str) -> dict | None:
    """Get a single repo by name. Returns dict or None."""
    from nullrealm.registry.models import Repository

    session_factory = _get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Repository).where(Repository.name == name)
        )
        repo = result.scalar_one_or_none()
        return _repo_to_dict(repo) if repo else None


def _repo_to_dict(repo) -> dict:
    """Convert a Repository ORM object to a plain dict."""
    return {
        "name": repo.name,
        "url": repo.url,
        "branch": repo.branch,
        "auth_type": repo.auth_type,
        "status": repo.status,
        "chunk_count": repo.chunk_count,
        "file_count": repo.file_count,
        "last_indexed_at": str(repo.last_indexed_at) if repo.last_indexed_at else None,
        "index_error": repo.index_error,
        "dep_map": repo.dep_map,
        "created_at": str(repo.created_at) if repo.created_at else None,
        "updated_at": str(repo.updated_at) if repo.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def _derive_repo_name(url: str) -> str:
    """Extract repo name from URL: github.com/org/repo.git -> repo"""
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


async def clone_or_pull(
    url: str,
    branch: str = "main",
    repo_name: str = "",
    auth_type: str = "public",
) -> Path:
    """Clone repo (or pull if already cached). Returns path to local clone.

    When auth_type="token", rewrites HTTPS URLs to include GITHUB_TOKEN
    for private repository access.
    """
    if not repo_name:
        repo_name = _derive_repo_name(url)

    # Inject PAT for private repos
    clone_url = url
    if auth_type == "token":
        token = os.getenv("GITHUB_TOKEN", "")
        if token and url.startswith("https://"):
            clone_url = url.replace("https://", f"https://{token}@")

    repo_dir = Path(CACHE_DIR) / repo_name
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if (repo_dir / ".git").exists():
        logger.info("Pulling %s (cached at %s)", url, repo_dir)
        proc = await asyncio.to_thread(
            subprocess.run, ["git", "pull"], cwd=repo_dir, capture_output=True, text=True
        )
    else:
        logger.info("Cloning %s branch=%s to %s", url, branch, repo_dir)
        proc = await asyncio.to_thread(
            subprocess.run,
            ["git", "clone", "--branch", branch, "--depth", "1", clone_url, str(repo_dir)],
            capture_output=True, text=True,
        )

    if proc.returncode != 0:
        raise RuntimeError(f"Git failed: {proc.stderr}")
    return repo_dir


# ---------------------------------------------------------------------------
# Indexing pipeline
# ---------------------------------------------------------------------------


async def index_repository(
    url: str,
    branch: str = "main",
    repo_name: str = "",
    auth_type: str = "public",
    embed: bool = True,
    graph: bool = True,
    generate_summary: bool = True,
) -> dict:
    """Clone/pull a repo and run the full indexing pipeline."""
    if not repo_name:
        repo_name = _derive_repo_name(url)

    repo_dir = await clone_or_pull(url, branch, repo_name, auth_type=auth_type)

    from nullrealm.context.indexer import index_repo
    chunks, rels, dep_map, service_analysis = await index_repo(
        str(repo_dir), embed=embed, graph=graph, repo_name=repo_name,
    )

    # Count unique files
    unique_files = set()
    for c in chunks:
        unique_files.add(c.file_path)
    files_count = len(unique_files)

    summary_path = ""
    if generate_summary:
        try:
            from nullrealm.context.summaries import run as run_summaries
            summary_path = await run_summaries(str(repo_dir), "repo-indexes")
        except Exception:
            logger.warning("Summary generation failed", exc_info=True)

    return {
        "repo_name": repo_name,
        "url": url,
        "chunks": len(chunks),
        "files": files_count,
        "relationships": len(rels),
        "summary_path": summary_path or "",
        "dep_map": dep_map,
        "service_analysis": service_analysis,
    }


# ---------------------------------------------------------------------------
# Delete / list
# ---------------------------------------------------------------------------


async def delete_repository_index(repo_name: str) -> dict:
    """Remove all indexed data for a repository."""
    chunks_deleted = 0
    nodes_deleted = 0

    # Delete from pgvector
    try:
        from nullrealm.context.pgvector_store import PgVectorStore
        from sqlalchemy import text

        store = PgVectorStore()
        await store.init()
        async with store._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM code_embeddings WHERE repo = :repo"),
                {"repo": repo_name},
            )
            chunks_deleted = result.rowcount
        await store.close()
    except Exception:
        logger.warning("Failed to delete pgvector data for %s", repo_name, exc_info=True)

    # Delete from Neo4j using the repo property
    try:
        neo4j_uri = os.getenv("NEO4J_URI")
        if neo4j_uri:
            from nullrealm.context.neo4j_store import Neo4jStore
            neo4j = Neo4jStore()
            nodes_deleted = await neo4j.delete_by_repo(repo_name)
            await neo4j.close()
    except Exception:
        logger.warning("Failed to delete Neo4j data for %s", repo_name, exc_info=True)

    # Delete from repos table
    try:
        from nullrealm.registry.models import Repository
        session_factory = _get_session_factory()
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    sa_delete(Repository).where(Repository.name == repo_name)
                )
    except Exception:
        logger.warning("Failed to delete repos table row for %s", repo_name, exc_info=True)

    # Delete REPO_INDEX.md
    index_path = Path(f"repo-indexes/{repo_name}/REPO_INDEX.md")
    if index_path.exists():
        index_path.unlink()
        logger.info("Deleted %s", index_path)

    # Delete cached clone
    clone_dir = Path(CACHE_DIR) / repo_name
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
        logger.info("Deleted cached clone at %s", clone_dir)

    return {
        "repo_name": repo_name,
        "chunks_deleted": chunks_deleted,
        "nodes_deleted": nodes_deleted,
    }


async def list_indexed_repos() -> list[dict]:
    """List all repos from the repos table."""
    from nullrealm.registry.models import Repository

    try:
        session_factory = _get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(Repository).order_by(Repository.name)
            )
            repos = result.scalars().all()
            return [_repo_to_dict(r) for r in repos]
    except Exception:
        logger.warning("Failed to list repos from repos table", exc_info=True)
        return []
