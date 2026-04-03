"""Neo4j graph store for code relationships.

Stores CodeRelationship objects as a property graph and provides
neighbor, shortest-path, and service-map queries.

Symbol nodes carry a `repo` property for per-repository namespacing
and fast deletion.
"""

import logging
import os

from neo4j import AsyncGraphDatabase

logger = logging.getLogger(__name__)


class Neo4jStore:
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://neo4j.null-realm.svc.cluster.local:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "neo4j-null-realm")
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self):
        await self._driver.close()

    async def store_graph(self, relationships: list, repo_name: str = "") -> None:
        """Store CodeRelationship objects as graph edges.

        Args:
            relationships: List of CodeRelationship dataclass instances.
            repo_name: Repository name to tag on every Symbol node.
        """
        async with self._driver.session() as session:
            # Create indexes for fast lookups
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.name)"
            )
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.file)"
            )
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.repo)"
            )

            # Store in batches using UNWIND for performance
            BATCH_SIZE = 500
            rel_dicts = [
                {
                    "src_file": rel.source_file,
                    "src_symbol": rel.source_symbol,
                    "tgt_file": rel.target_file,
                    "tgt_symbol": rel.target_symbol,
                    "rel_type": rel.relationship,
                }
                for rel in relationships
            ]
            for i in range(0, len(rel_dicts), BATCH_SIZE):
                batch = rel_dicts[i : i + BATCH_SIZE]
                await session.run(
                    """
                    UNWIND $rels AS rel
                    MERGE (a:Symbol {file: rel.src_file, name: rel.src_symbol, repo: $repo})
                    MERGE (b:Symbol {file: rel.tgt_file, name: rel.tgt_symbol, repo: $repo})
                    MERGE (a)-[r:RELATES {type: rel.rel_type}]->(b)
                    SET a.type = COALESCE(a.type, 'unknown'),
                        b.type = COALESCE(b.type, 'unknown')
                    """,
                    rels=batch,
                    repo=repo_name,
                )
                logger.info("Stored Neo4j batch %d-%d of %d", i, i + len(batch), len(rel_dicts))

        # Log counts
        async with self._driver.session() as session:
            node_result = await session.run("MATCH (n:Symbol) RETURN count(n) AS cnt")
            node_record = await node_result.single()
            node_count = node_record["cnt"] if node_record else 0

            edge_result = await session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            edge_record = await edge_result.single()
            edge_count = edge_record["cnt"] if edge_record else 0

            logger.info("Graph now has %d nodes and %d edges", node_count, edge_count)

    async def delete_by_repo(self, repo_name: str) -> int:
        """Delete all Symbol nodes (and their relationships) for a given repo.

        Returns:
            Number of nodes deleted.
        """
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n:Symbol {repo: $repo}) DETACH DELETE n RETURN count(n) as deleted",
                repo=repo_name,
            )
            record = await result.single()
            deleted = record["deleted"] if record else 0
            logger.info("Deleted %d Neo4j nodes for repo '%s'", deleted, repo_name)
            return deleted

    async def query_neighbors(self, symbol: str, depth: int = 2) -> list:
        """Find all connected symbols within depth hops."""
        depth = int(depth)  # sanitize
        async with self._driver.session() as session:
            result = await session.run(
                f"""
                MATCH path = (a:Symbol)-[*1..{depth}]-(b:Symbol)
                WHERE a.name = $symbol
                RETURN DISTINCT b.file AS file, b.name AS name, b.type AS type,
                       length(path) AS distance
                ORDER BY distance
                LIMIT 50
                """,
                symbol=symbol,
            )
            return [dict(record) async for record in result]

    async def query_path(self, source: str, target: str) -> list:
        """Find shortest path between two symbols."""
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH path = shortestPath((a:Symbol)-[*..5]-(b:Symbol))
                WHERE a.name = $source AND b.name = $target
                RETURN [n IN nodes(path) | {file: n.file, name: n.name}] AS path_nodes,
                       [r IN relationships(path) | r.type] AS edge_types
                """,
                source=source,
                target=target,
            )
            return [dict(record) async for record in result]

    async def query_service_map(self) -> list:
        """Get all file-to-file connections."""
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (a:Symbol)-[r]->(b:Symbol)
                WHERE a.file <> b.file
                RETURN DISTINCT a.file AS source_file, r.type AS relationship,
                       b.file AS target_file
                ORDER BY source_file
                """
            )
            return [dict(record) async for record in result]
