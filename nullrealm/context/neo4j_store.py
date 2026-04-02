"""Neo4j graph store for code relationships.

Stores CodeRelationship objects as a property graph and provides
neighbor, shortest-path, and service-map queries.
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

    async def store_graph(self, relationships: list):
        """Store CodeRelationship objects as graph edges."""
        async with self._driver.session() as session:
            # Create indexes for fast lookups
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.name)"
            )
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.file)"
            )

            # Store in batches
            for rel in relationships:
                await session.run(
                    """
                    MERGE (a:Symbol {file: $src_file, name: $src_symbol})
                    MERGE (b:Symbol {file: $tgt_file, name: $tgt_symbol})
                    MERGE (a)-[r:RELATES {type: $rel_type}]->(b)
                    SET a.type = COALESCE(a.type, 'unknown'),
                        b.type = COALESCE(b.type, 'unknown')
                    """,
                    src_file=rel.source_file,
                    src_symbol=rel.source_symbol,
                    tgt_file=rel.target_file,
                    tgt_symbol=rel.target_symbol,
                    rel_type=rel.relationship,
                )

        # Log counts
        async with self._driver.session() as session:
            node_result = await session.run("MATCH (n:Symbol) RETURN count(n) AS cnt")
            node_record = await node_result.single()
            node_count = node_record["cnt"] if node_record else 0

            edge_result = await session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            edge_record = await edge_result.single()
            edge_count = edge_record["cnt"] if edge_record else 0

            logger.info("Graph now has %d nodes and %d edges", node_count, edge_count)

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
