"""Repository management: clone, index, delete, list."""

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = os.getenv("REPO_CACHE_DIR", "/tmp/null-realm-repos")


def _derive_repo_name(url: str) -> str:
    """Extract repo name from URL: github.com/org/repo.git -> repo"""
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


async def clone_or_pull(url: str, branch: str = "main", repo_name: str = "") -> Path:
    """Clone repo (or pull if already cached). Returns path to local clone."""
    if not repo_name:
        repo_name = _derive_repo_name(url)
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
            ["git", "clone", "--branch", branch, "--depth", "1", url, str(repo_dir)],
            capture_output=True, text=True,
        )

    if proc.returncode != 0:
        raise RuntimeError(f"Git failed: {proc.stderr}")
    return repo_dir


async def index_repository(
    url: str,
    branch: str = "main",
    repo_name: str = "",
    embed: bool = True,
    graph: bool = True,
    generate_summary: bool = True,
) -> dict:
    """Clone/pull a repo and run the full indexing pipeline."""
    if not repo_name:
        repo_name = _derive_repo_name(url)

    repo_dir = await clone_or_pull(url, branch, repo_name)

    from nullrealm.context.indexer import index_repo
    chunks, rels = await index_repo(str(repo_dir), embed=embed, graph=graph)

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
        "relationships": len(rels),
        "summary_path": summary_path or "",
    }


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

    # Delete from Neo4j
    # NOTE: Symbol nodes don't have a 'repo' property yet.
    # File paths are relative to repo root, so this works if repos have
    # unique top-level dirs. Proper fix: add 'repo' property to nodes.
    try:
        neo4j_uri = os.getenv("NEO4J_URI")
        if neo4j_uri:
            from nullrealm.context.neo4j_store import Neo4jStore
            neo4j = Neo4jStore()
            async with neo4j._driver.session() as session:
                result = await session.run(
                    "MATCH (n:Symbol) WHERE n.file STARTS WITH $prefix "
                    "DETACH DELETE n RETURN count(n) as deleted",
                    prefix=f"{repo_name}/",
                )
                record = await result.single()
                nodes_deleted = record["deleted"] if record else 0
            await neo4j.close()
    except Exception:
        logger.warning("Failed to delete Neo4j data for %s", repo_name, exc_info=True)

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
    """List all indexed repos with stats from pgvector."""
    try:
        from nullrealm.context.pgvector_store import PgVectorStore
        from sqlalchemy import text

        store = PgVectorStore()
        await store.init()
        async with store._engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT repo,
                       COUNT(*) as chunks,
                       COUNT(DISTINCT file_path) as files,
                       MIN(created_at)::text as first_indexed
                FROM code_embeddings
                GROUP BY repo
                ORDER BY repo
            """))
            repos = [dict(row._mapping) for row in result]
        await store.close()
        return repos
    except Exception:
        logger.warning("Failed to list repos", exc_info=True)
        return []
