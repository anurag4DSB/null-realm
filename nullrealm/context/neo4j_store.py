"""Neo4j graph store for code relationships.

Stores CodeRelationship objects as a property graph and provides
neighbor, shortest-path, service-map, and service-topology queries.

Symbol nodes carry a `repo` property for per-repository namespacing
and fast deletion.  Service, Endpoint, Topic, and InfraService nodes
model the service-level topology; XREF edges connect symbols across
repositories.
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
            # TEXT indexes for name/file — required for CONTAINS/ENDS WITH in cross-repo XREF queries
            # RANGE indexes for repo — used for exact match lookups and delete_by_repo
            await session.run(
                "CREATE TEXT INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.name)"
            )
            await session.run(
                "CREATE TEXT INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.file)"
            )
            await session.run(
                "CREATE RANGE INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.repo)"
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

    async def store_service_graph(self, analysis) -> dict:
        """Store service-level topology from ServiceAnalysis.

        Args:
            analysis: ServiceAnalysis dataclass with connections, endpoints,
                      topics, and infra_services attributes.
        Returns:
            dict with counts of nodes/edges created.
        """
        counts = {"services": 0, "connections": 0, "endpoints": 0, "topics": 0, "infra": 0}

        async with self._driver.session() as session:
            # Create indexes for new node labels
            for label, prop in [
                ("Service", "name"),
                ("Endpoint", "path"),
                ("Topic", "name"),
                ("InfraService", "name"),
            ]:
                await session.run(
                    f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
                )

            # --- Service nodes + connections ---
            BATCH_SIZE = 500
            if hasattr(analysis, "connections") and analysis.connections:
                conn_dicts = [
                    {
                        "source": c.source,
                        "source_repo": getattr(c, "source_repo", c.source),
                        "source_desc": getattr(c, "source_description", ""),
                        "target": c.target,
                        "target_repo": getattr(c, "target_repo", c.target),
                        "target_desc": getattr(c, "target_description", ""),
                        "rel_type": c.rel_type,
                        "package": getattr(c, "package", ""),
                        "via": getattr(c, "via", ""),
                        "library": getattr(c, "library", ""),
                        "port": getattr(c, "port", 0),
                        "purpose": getattr(c, "purpose", ""),
                        "path": getattr(c, "path", ""),
                    }
                    for c in analysis.connections
                ]
                for i in range(0, len(conn_dicts), BATCH_SIZE):
                    batch = conn_dicts[i : i + BATCH_SIZE]

                    # MERGE service nodes
                    await session.run(
                        """
                        UNWIND $conns AS c
                        MERGE (a:Service {name: c.source})
                        SET a.repo = c.source_repo, a.description = c.source_desc
                        MERGE (b:Service {name: c.target})
                        SET b.repo = c.target_repo, b.description = c.target_desc
                        """,
                        conns=batch,
                    )

                    # DEPENDS_ON
                    dep_batch = [c for c in batch if c["rel_type"] == "DEPENDS_ON"]
                    if dep_batch:
                        await session.run(
                            """
                            UNWIND $conns AS c
                            MATCH (a:Service {name: c.source}), (b:Service {name: c.target})
                            MERGE (a)-[:DEPENDS_ON {package: c.package}]->(b)
                            """,
                            conns=dep_batch,
                        )

                    # HTTP_CALLS
                    http_batch = [c for c in batch if c["rel_type"] == "HTTP_CALLS"]
                    if http_batch:
                        await session.run(
                            """
                            UNWIND $conns AS c
                            MATCH (a:Service {name: c.source}), (b:Service {name: c.target})
                            MERGE (a)-[:HTTP_CALLS {port: c.port, purpose: c.purpose}]->(b)
                            """,
                            conns=http_batch,
                        )

                    # USES_CLIENT
                    client_batch = [c for c in batch if c["rel_type"] == "USES_CLIENT"]
                    if client_batch:
                        await session.run(
                            """
                            UNWIND $conns AS c
                            MATCH (a:Service {name: c.source}), (b:Service {name: c.target})
                            MERGE (a)-[:USES_CLIENT {via: c.via}]->(b)
                            """,
                            conns=client_batch,
                        )

                    # USES_INFRA
                    infra_batch = [c for c in batch if c["rel_type"] == "USES_INFRA"]
                    if infra_batch:
                        await session.run(
                            """
                            UNWIND $conns AS c
                            MERGE (i:InfraService {name: c.target})
                            SET i.type = c.purpose
                            WITH c, i
                            MATCH (a:Service {name: c.source})
                            MERGE (a)-[:USES_INFRA {purpose: c.purpose}]->(i)
                            """,
                            conns=infra_batch,
                        )
                        counts["infra"] += len(infra_batch)

                    # CONFIGURED_BY (Federation config → Service)
                    config_batch = [c for c in batch if c["rel_type"] == "CONFIGURED_BY"]
                    if config_batch:
                        await session.run(
                            """
                            UNWIND $conns AS c
                            MATCH (a:Service {name: c.source})
                            MERGE (cfg:Symbol {file: c.path, name: c.target, repo: "Federation"})
                            SET cfg.type = "config"
                            MERGE (a)-[:CONFIGURED_BY {file: c.path}]->(cfg)
                            """,
                            conns=config_batch,
                        )

                    # BUILT_FROM (Docker image → Service/Repo)
                    built_batch = [c for c in batch if c["rel_type"] == "BUILT_FROM"]
                    if built_batch:
                        await session.run(
                            """
                            UNWIND $conns AS c
                            MATCH (a:Service {name: c.source})
                            MERGE (b:Service {name: c.target})
                            MERGE (a)-[:BUILT_FROM {image: c.via}]->(b)
                            """,
                            conns=built_batch,
                        )

                counts["services"] += len({c["source"] for c in conn_dicts} | {c["target"] for c in conn_dicts})
                counts["connections"] += len(conn_dicts)

            # --- Endpoints ---
            if hasattr(analysis, "endpoints") and analysis.endpoints:
                ep_dicts = [
                    {
                        "path": ep.path,
                        "method": getattr(ep, "method", "GET"),
                        "service": ep.service,
                        "description": getattr(ep, "description", ""),
                    }
                    for ep in analysis.endpoints
                ]
                for i in range(0, len(ep_dicts), BATCH_SIZE):
                    batch = ep_dicts[i : i + BATCH_SIZE]
                    await session.run(
                        """
                        UNWIND $eps AS ep
                        MERGE (e:Endpoint {path: ep.path, service: ep.service})
                        SET e.method = ep.method, e.description = ep.description
                        WITH ep, e
                        MATCH (s:Service {name: ep.service})
                        MERGE (s)-[:EXPOSES]->(e)
                        """,
                        eps=batch,
                    )
                counts["endpoints"] += len(ep_dicts)

            # --- Topics ---
            if hasattr(analysis, "topics") and analysis.topics:
                topic_dicts = [
                    {
                        "name": t.name,
                        "description": getattr(t, "description", ""),
                        "service": t.service,
                        "role": t.role,  # "PRODUCES" or "CONSUMES"
                    }
                    for t in analysis.topics
                ]
                for i in range(0, len(topic_dicts), BATCH_SIZE):
                    batch = topic_dicts[i : i + BATCH_SIZE]
                    # MERGE topic nodes
                    await session.run(
                        """
                        UNWIND $topics AS t
                        MERGE (tp:Topic {name: t.name})
                        SET tp.description = t.description
                        """,
                        topics=batch,
                    )
                    # PRODUCES
                    prod_batch = [t for t in batch if t["role"] == "PRODUCES"]
                    if prod_batch:
                        await session.run(
                            """
                            UNWIND $topics AS t
                            MATCH (s:Service {name: t.service}), (tp:Topic {name: t.name})
                            MERGE (s)-[:PRODUCES]->(tp)
                            """,
                            topics=prod_batch,
                        )
                    # CONSUMES
                    cons_batch = [t for t in batch if t["role"] == "CONSUMES"]
                    if cons_batch:
                        await session.run(
                            """
                            UNWIND $topics AS t
                            MATCH (s:Service {name: t.service}), (tp:Topic {name: t.name})
                            MERGE (s)-[:CONSUMES]->(tp)
                            """,
                            topics=cons_batch,
                        )
                counts["topics"] += len(topic_dicts)

        logger.info(
            "Created %d service connections, %d endpoints, %d topics",
            counts["connections"],
            counts["endpoints"],
            counts["topics"],
        )
        return counts

    async def link_cross_repo(self, repo_name: str, dep_map: dict[str, str]) -> int:
        """Create XREF edges from this repo's orphan CALLS to actual symbols in dep repos.

        For each dependency, finds files in *repo_name* that import the dependency
        package, then matches unresolved CALLS from those files against symbols
        defined in the dependency repo.

        Args:
            repo_name: The repo being linked (e.g., "cloudserver").
            dep_map: ``{package_name: target_repo_name}`` from package.json.
        Returns:
            Number of XREF edges created.
        """
        total_created = 0
        async with self._driver.session() as session:
            for dep_name, dep_repo in dep_map.items():
                # Step 1: find files in this repo that import the dependency
                import_result = await session.run(
                    """
                    MATCH (imp:Symbol {repo: $repo})-[:RELATES {type: "IMPORTS"}]->(dep:Symbol {name: $dep_name})
                    RETURN DISTINCT imp.file AS file
                    """,
                    repo=repo_name,
                    dep_name=dep_name,
                )
                importing_files = [record["file"] async for record in import_result]
                if not importing_files:
                    continue

                # Step 2: match orphan CALLS to symbols in the dep repo
                xref_result = await session.run(
                    """
                    MATCH (caller:Symbol {repo: $repo})-[:RELATES {type: "CALLS"}]->(orphan:Symbol {file: ""})
                    WHERE caller.file IN $importing_files
                    WITH caller, orphan
                    MATCH (target:Symbol {repo: $dep_repo})
                    WHERE target.file <> ""
                      AND (target.name = orphan.name OR target.name CONTAINS ("." + orphan.name))
                    MERGE (caller)-[:XREF {type: "CALLS", package: $dep_name}]->(target)
                    RETURN count(*) AS created
                    """,
                    repo=repo_name,
                    importing_files=importing_files,
                    dep_repo=dep_repo,
                    dep_name=dep_name,
                )
                record = await xref_result.single()
                created = record["created"] if record else 0
                if created:
                    logger.info(
                        "Linked %d XREF edges: %s -> %s (via %s)",
                        created, repo_name, dep_repo, dep_name,
                    )
                total_created += created

        logger.info("Total XREF edges created for '%s': %d", repo_name, total_created)
        return total_created

    async def query_service_topology(self) -> list:
        """Return the complete service topology graph.

        Returns every Service node and its outgoing relationships to other
        Service, Endpoint, Topic, and InfraService nodes.
        """
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (a:Service)-[r]->(b)
                WHERE type(r) IN [
                    'DEPENDS_ON', 'HTTP_CALLS', 'USES_CLIENT',
                    'EXPOSES', 'PRODUCES', 'CONSUMES', 'USES_INFRA',
                    'CONFIGURED_BY', 'BUILT_FROM'
                ]
                RETURN a.name AS source, type(r) AS rel_type,
                       CASE
                           WHEN b:Service THEN b.name
                           WHEN b:Endpoint THEN b.path
                           WHEN b:Topic THEN b.name
                           WHEN b:InfraService THEN b.name
                           WHEN b:Symbol THEN b.name
                       END AS target,
                       properties(r) AS props
                ORDER BY a.name, type(r)
                """
            )
            return [dict(record) async for record in result]

    async def query_service_deps(self, service_name: str) -> list:
        """Return all dependencies of a specific service.

        Includes DEPENDS_ON, HTTP_CALLS, USES_CLIENT, and USES_INFRA
        relationships originating from the named service.
        """
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (s:Service {name: $name})-[r]->(target)
                WHERE type(r) IN [
                    'DEPENDS_ON', 'HTTP_CALLS', 'USES_CLIENT',
                    'EXPOSES', 'PRODUCES', 'CONSUMES', 'USES_INFRA',
                    'CONFIGURED_BY', 'BUILT_FROM'
                ]
                RETURN type(r) AS rel_type,
                       CASE
                           WHEN target:Service THEN target.name
                           WHEN target:Endpoint THEN target.path
                           WHEN target:Topic THEN target.name
                           WHEN target:InfraService THEN target.name
                           WHEN target:Symbol THEN target.name
                       END AS target,
                       labels(target) AS target_labels,
                       properties(r) AS props
                ORDER BY type(r), target
                """,
                name=service_name,
            )
            return [dict(record) async for record in result]

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
        """Find all connected symbols within depth hops.

        Traverses both intra-repo RELATES and cross-repo XREF edges so
        that queries can follow symbol references across repository
        boundaries.
        """
        depth = int(depth)  # sanitize
        async with self._driver.session() as session:
            result = await session.run(
                f"""
                MATCH path = (a:Symbol)-[:RELATES|XREF*1..{depth}]-(b:Symbol)
                WHERE a.name = $symbol
                RETURN DISTINCT b.file AS file, b.name AS name, b.type AS type,
                       b.repo AS repo, length(path) AS distance
                ORDER BY distance
                LIMIT 50
                """,
                symbol=symbol,
            )
            return [dict(record) async for record in result]

    async def query_path(self, source: str, target: str) -> list:
        """Find shortest path between two symbols.

        Traverses both RELATES and XREF edges so paths can span
        repository boundaries (e.g. cloudserver → Arsenal).
        """
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH path = shortestPath((a:Symbol)-[:RELATES|XREF*..5]-(b:Symbol))
                WHERE a.name = $source AND b.name = $target
                RETURN [n IN nodes(path) | {file: n.file, name: n.name, repo: n.repo}] AS path_nodes,
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
