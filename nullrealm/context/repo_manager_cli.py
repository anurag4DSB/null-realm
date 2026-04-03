"""CLI entrypoint for Argo repo indexing pods.

Runs inside an Argo Workflow pod with git installed.
Updates the repos table with status/stats as indexing progresses.
"""

import argparse
import asyncio
import logging
import os

from nullrealm.context.repo_manager import index_repository, update_repo_status

logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Index a git repository")
    parser.add_argument("--url", required=True, help="Git clone URL")
    parser.add_argument("--branch", default="main", help="Branch to clone")
    parser.add_argument("--name", required=True, help="Repository name (unique key)")
    parser.add_argument("--auth-type", default="public", help="Auth type: public or token")
    parser.add_argument("--mode", default="code", choices=["code", "federation"],
                        help="Indexing mode: 'code' for tree-sitter, 'federation' for config/doc chunking")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info(
        "Starting repo indexing: name=%s url=%s branch=%s auth_type=%s mode=%s",
        args.name, args.url, args.branch, args.auth_type, args.mode,
    )

    try:
        await update_repo_status(args.name, "indexing")

        if args.mode == "federation":
            # Federation mode: text chunking of config templates, docs, playbooks
            from pathlib import Path
            from nullrealm.context.repo_manager import clone_or_pull
            from nullrealm.context.service_analyzer import index_federation, ServiceAnalysis
            from nullrealm.context.embeddings import embed_texts
            from nullrealm.context.pgvector_store import PgVectorStore

            repo_dir = await clone_or_pull(args.url, args.branch, args.name, auth_type=args.auth_type)
            chunks, connections = index_federation(Path(repo_dir))

            if chunks:
                # Embed and store in pgvector
                texts = [c.text for c in chunks]
                logger.info("Embedding %d Federation chunks...", len(texts))
                embeddings = embed_texts(texts)

                store = PgVectorStore()
                await store.init()
                await store.store_embeddings(chunks, embeddings, repo_name=args.name)
                await store.close()
                logger.info("Stored %d Federation chunks in pgvector", len(chunks))

            # Store service topology in Neo4j
            neo4j_uri = os.getenv("NEO4J_URI")
            if neo4j_uri and connections:
                try:
                    from nullrealm.context.neo4j_store import Neo4jStore
                    neo4j = Neo4jStore()
                    analysis = ServiceAnalysis(
                        repo_name=args.name,
                        dep_map={},
                        connections=connections,
                        endpoints=[],
                        topics=[],
                    )
                    svc_stats = await neo4j.store_service_graph(analysis)
                    logger.info("Federation service graph: %s", svc_stats)
                    await neo4j.close()
                except Exception:
                    logger.warning("Federation service graph storage failed", exc_info=True)

            result = {
                "chunks": len(chunks),
                "files": len(set(c.file_path for c in chunks)),
            }
        else:
            # Code mode: tree-sitter AST parsing (existing flow)
            result = await index_repository(
                args.url,
                branch=args.branch,
                repo_name=args.name,
                auth_type=args.auth_type,
            )

            # Store service graph and create cross-repo links
            neo4j_uri = os.getenv("NEO4J_URI")
            if neo4j_uri and result.get("service_analysis"):
                try:
                    from nullrealm.context.neo4j_store import Neo4jStore
                    neo4j = Neo4jStore()
                    analysis = result["service_analysis"]
                    svc_stats = await neo4j.store_service_graph(analysis)
                    logger.info("Service graph: %s", svc_stats)
                    dep_map = result.get("dep_map", {})
                    if dep_map:
                        xref_count = await neo4j.link_cross_repo(args.name, dep_map)
                        logger.info("Cross-repo links: %d XREF edges created", xref_count)
                    await neo4j.close()
                except Exception:
                    logger.warning("Service graph/XREF linking failed", exc_info=True)

        # Store dep_map if available
        dep_map = result.get("dep_map", {})
        await update_repo_status(
            args.name,
            "ready",
            chunk_count=result["chunks"],
            file_count=result.get("files", 0),
            dep_map=dep_map if dep_map else None,
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
