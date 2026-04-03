"""CLI entrypoint for Argo repo indexing pods.

Runs inside an Argo Workflow pod with git installed.
Updates the repos table with status/stats as indexing progresses.
"""

import argparse
import asyncio
import logging

from nullrealm.context.repo_manager import index_repository, update_repo_status

logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Index a git repository")
    parser.add_argument("--url", required=True, help="Git clone URL")
    parser.add_argument("--branch", default="main", help="Branch to clone")
    parser.add_argument("--name", required=True, help="Repository name (unique key)")
    parser.add_argument("--auth-type", default="public", help="Auth type: public or token")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info(
        "Starting repo indexing: name=%s url=%s branch=%s auth_type=%s",
        args.name, args.url, args.branch, args.auth_type,
    )

    try:
        await update_repo_status(args.name, "indexing")
        result = await index_repository(
            args.url,
            branch=args.branch,
            repo_name=args.name,
            auth_type=args.auth_type,
        )
        await update_repo_status(
            args.name,
            "ready",
            chunk_count=result["chunks"],
            file_count=result.get("files", 0),
        )
        logger.info(
            "Indexing complete: %d chunks, %d files",
            result["chunks"], result.get("files", 0),
        )
    except Exception as e:
        logger.error("Indexing failed: %s", e, exc_info=True)
        await update_repo_status(args.name, "failed", error=str(e))
        raise


if __name__ == "__main__":
    asyncio.run(main())
