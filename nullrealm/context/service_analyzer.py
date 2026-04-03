"""Service-level relationship analyzer for indexed code repositories.

Post-indexing pass that detects inter-service connections, API endpoints,
and Kafka topic usage from CodeChunks and repository metadata (package.json,
go.mod, requirements.txt).  Returns structured data suitable for Neo4j storage.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from nullrealm.context.indexer import CodeChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ServiceConnection:
    """A directed service-to-service dependency."""

    source: str  # e.g. "cloudserver"
    target: str  # e.g. "vault"
    rel_type: str  # "DEPENDS_ON", "HTTP_CALLS", "USES_CLIENT"
    properties: dict = field(default_factory=dict)


@dataclass
class ServiceEndpoint:
    """An HTTP route exposed by a service."""

    service: str  # e.g. "backbeat"
    path: str  # e.g. "/_/crr/metrics/all"
    method: str  # e.g. "GET"
    handler_symbol: str = ""


@dataclass
class KafkaTopicUsage:
    """A service's relationship to a Kafka topic."""

    service: str  # e.g. "backbeat"
    topic: str  # e.g. "backbeat-replication"
    role: str  # "producer" or "consumer"


@dataclass
class ServiceAnalysis:
    """Aggregated analysis results for a single repository."""

    repo_name: str
    dep_map: dict[str, str]  # {package_name: github_repo_name}
    connections: list[ServiceConnection] = field(default_factory=list)
    endpoints: list[ServiceEndpoint] = field(default_factory=list)
    topics: list[KafkaTopicUsage] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Client-library → service mapping
# ---------------------------------------------------------------------------

CLIENT_LIBRARY_MAP: dict[str, str] = {
    "vaultclient": "vault",
    "bucketclient": "bucketd",
    "scubaclient": "scuba",
    "sproxydclient": "sproxyd",
}

# ---------------------------------------------------------------------------
# Known Kafka topics
# ---------------------------------------------------------------------------

KNOWN_TOPICS: list[str] = [
    "backbeat-replication",
    "backbeat-replication-status",
    "backbeat-replication-failed",
    "backbeat-metrics",
    "backbeat-gc",
]

# ---------------------------------------------------------------------------
# Dependency-file parsers
# ---------------------------------------------------------------------------

_SCALITY_RE = re.compile(r"scality/([^#\s\"']+)")


def parse_package_json(repo_path: Path) -> dict[str, str]:
    """Extract Scality GitHub dependencies from ``package.json``.

    Returns a mapping ``{npm_package_name: github_repo_name}``.
    """
    pkg_json = repo_path / "package.json"
    if not pkg_json.exists():
        return {}
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse %s: %s", pkg_json, exc)
        return {}

    deps: dict[str, str] = {
        **data.get("dependencies", {}),
        **data.get("devDependencies", {}),
    }
    dep_map: dict[str, str] = {}
    for name, spec in deps.items():
        match = _SCALITY_RE.search(str(spec))
        if match:
            repo_name = match.group(1)
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            dep_map[name] = repo_name
    return dep_map


def _parse_go_mod(repo_path: Path) -> dict[str, str]:
    """Extract Scality Go module dependencies from ``go.mod``."""
    go_mod = repo_path / "go.mod"
    if not go_mod.exists():
        return {}
    try:
        text = go_mod.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read %s: %s", go_mod, exc)
        return {}

    dep_map: dict[str, str] = {}
    # Matches lines like: github.com/scality/backbeat v1.2.3
    for match in re.finditer(r"github\.com/scality/(\S+)\s", text):
        mod_name = match.group(1)
        dep_map[f"github.com/scality/{mod_name}"] = mod_name
    return dep_map


def _parse_requirements_txt(repo_path: Path) -> dict[str, str]:
    """Extract Scality Python dependencies from ``requirements.txt``."""
    req_txt = repo_path / "requirements.txt"
    if not req_txt.exists():
        return {}
    try:
        text = req_txt.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read %s: %s", req_txt, exc)
        return {}

    dep_map: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SCALITY_RE.search(line)
        if match:
            repo_name = match.group(1)
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            # Use the first token as the package name
            pkg_name = re.split(r"[><=@\s]", line)[0]
            dep_map[pkg_name] = repo_name
    return dep_map


def parse_all_deps(repo_path: Path) -> dict[str, str]:
    """Parse all supported dependency manifests and merge results."""
    dep_map: dict[str, str] = {}
    dep_map.update(parse_package_json(repo_path))
    dep_map.update(_parse_go_mod(repo_path))
    dep_map.update(_parse_requirements_txt(repo_path))
    return dep_map


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------

# Pre-compiled patterns used by detect_client_patterns
_CLIENT_REQUIRE_RE = re.compile(
    r"""(?:require\s*\(\s*['"]|from\s+['"]|import\s+['"])"""
    r"""(vaultclient|bucketclient|scubaclient|sproxydclient)""",
)


def detect_client_patterns(
    chunks: list[CodeChunk],
    repo_name: str,
) -> list[ServiceConnection]:
    """Detect known client-library imports across all chunks."""
    seen: set[tuple[str, str, str]] = set()
    connections: list[ServiceConnection] = []

    for chunk in chunks:
        for match in _CLIENT_REQUIRE_RE.finditer(chunk.text):
            lib_name = match.group(1)
            target = CLIENT_LIBRARY_MAP[lib_name]
            key = (repo_name, target, "USES_CLIENT")
            if key not in seen:
                seen.add(key)
                connections.append(
                    ServiceConnection(
                        source=repo_name,
                        target=target,
                        rel_type="USES_CLIENT",
                        properties={"library": lib_name},
                    )
                )
    return connections


# Pre-compiled patterns used by detect_http_patterns
_HTTP_PROXY_RE = re.compile(r"httpProxy|createProxyServer")
_HTTP_REQUEST_RE = re.compile(r"https?\.request")
_CONFIG_HOST_RE = re.compile(r"config\.(\w+)\.(host|port)")


def detect_http_patterns(
    chunks: list[CodeChunk],
    repo_name: str,
) -> list[ServiceConnection]:
    """Detect HTTP proxy / direct-call patterns and config-based hosts."""
    seen: set[tuple[str, str, str]] = set()
    connections: list[ServiceConnection] = []

    for chunk in chunks:
        text = chunk.text

        # Pattern 1 — HTTP proxy
        if _HTTP_PROXY_RE.search(text):
            key = (repo_name, "proxy-target", "HTTP_CALLS")
            if key not in seen:
                seen.add(key)
                connections.append(
                    ServiceConnection(
                        source=repo_name,
                        target="proxy-target",
                        rel_type="HTTP_CALLS",
                        properties={"pattern": "httpProxy", "file": chunk.file_path},
                    )
                )

        # Pattern 2 — direct http.request / https.request
        if _HTTP_REQUEST_RE.search(text):
            key = (repo_name, "http-target", "HTTP_CALLS")
            if key not in seen:
                seen.add(key)
                connections.append(
                    ServiceConnection(
                        source=repo_name,
                        target="http-target",
                        rel_type="HTTP_CALLS",
                        properties={"pattern": "http.request", "file": chunk.file_path},
                    )
                )

        # Pattern 3 — config.<service>.host / config.<service>.port
        for m in _CONFIG_HOST_RE.finditer(text):
            service = m.group(1)
            key = (repo_name, service, "HTTP_CALLS")
            if key not in seen:
                seen.add(key)
                connections.append(
                    ServiceConnection(
                        source=repo_name,
                        target=service,
                        rel_type="HTTP_CALLS",
                        properties={"pattern": "config-host", "config_key": m.group(0)},
                    )
                )

    return connections


# Pre-compiled patterns for Kafka detection
_KAFKA_PRODUCER_RE = re.compile(r"BackbeatProducer|new\s+Producer")
_KAFKA_CONSUMER_RE = re.compile(r"BackbeatConsumer|new\s+Consumer")
_KAFKA_TOPIC_RE = re.compile(
    r"""['"]([a-z]+-[a-z][\w-]*)['"]""",
)


def detect_kafka_patterns(
    chunks: list[CodeChunk],
    repo_name: str,
) -> list[KafkaTopicUsage]:
    """Detect Kafka producer/consumer patterns and topic references."""
    seen: set[tuple[str, str, str]] = set()
    topics: list[KafkaTopicUsage] = []

    for chunk in chunks:
        text = chunk.text
        is_producer = bool(_KAFKA_PRODUCER_RE.search(text))
        is_consumer = bool(_KAFKA_CONSUMER_RE.search(text))

        if not is_producer and not is_consumer:
            continue

        # Look for known topic names in the same chunk
        for topic_name in KNOWN_TOPICS:
            if topic_name in text:
                if is_producer:
                    key = (repo_name, topic_name, "producer")
                    if key not in seen:
                        seen.add(key)
                        topics.append(
                            KafkaTopicUsage(
                                service=repo_name,
                                topic=topic_name,
                                role="producer",
                            )
                        )
                if is_consumer:
                    key = (repo_name, topic_name, "consumer")
                    if key not in seen:
                        seen.add(key)
                        topics.append(
                            KafkaTopicUsage(
                                service=repo_name,
                                topic=topic_name,
                                role="consumer",
                            )
                        )

        # Also pick up topic-like strings that match known patterns
        for m in _KAFKA_TOPIC_RE.finditer(text):
            candidate = m.group(1)
            if candidate.startswith("backbeat-") and candidate not in {
                t for _, t, _ in seen
            }:
                role = "producer" if is_producer else "consumer"
                key = (repo_name, candidate, role)
                if key not in seen:
                    seen.add(key)
                    topics.append(
                        KafkaTopicUsage(
                            service=repo_name,
                            topic=candidate,
                            role=role,
                        )
                    )

    return topics


# Pre-compiled patterns for Express-style routes
_ROUTE_METHOD_RE = re.compile(
    r"""(?:router|app)\.(get|post|put|delete|patch|use|all|head|options)"""
    r"""\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_ROUTE_PATH_RE = re.compile(r"""['"](/\_/[a-z][a-zA-Z/\-]*)['"]""")


def detect_api_routes(
    chunks: list[CodeChunk],
    repo_name: str,
) -> list[ServiceEndpoint]:
    """Detect Express-style route definitions."""
    seen: set[tuple[str, str, str]] = set()
    endpoints: list[ServiceEndpoint] = []

    for chunk in chunks:
        text = chunk.text

        # Pattern 1 — router.get('/path', handler) / app.use('/path', handler)
        for m in _ROUTE_METHOD_RE.finditer(text):
            method = m.group(1).upper()
            path = m.group(2)
            key = (repo_name, path, method)
            if key not in seen:
                seen.add(key)
                endpoints.append(
                    ServiceEndpoint(
                        service=repo_name,
                        path=path,
                        method=method,
                        handler_symbol=chunk.symbol_name,
                    )
                )

        # Pattern 2 — bare /_/ path strings (common internal endpoints)
        for m in _ROUTE_PATH_RE.finditer(text):
            path = m.group(1)
            key = (repo_name, path, "ROUTE")
            if key not in seen:
                seen.add(key)
                endpoints.append(
                    ServiceEndpoint(
                        service=repo_name,
                        path=path,
                        method="ROUTE",
                        handler_symbol=chunk.symbol_name,
                    )
                )

    return endpoints


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_service(
    repo_name: str,
    repo_path: Path,
    chunks: list[CodeChunk],
) -> ServiceAnalysis:
    """Run all service-level detectors and return combined results.

    Args:
        repo_name: Short name of the repository (e.g. ``"cloudserver"``).
        repo_path: Filesystem path to the repository root.
        chunks: Pre-parsed ``CodeChunk`` list from the indexer.

    Returns:
        A :class:`ServiceAnalysis` containing all detected connections,
        endpoints, and Kafka topic usages.
    """
    dep_map = parse_all_deps(repo_path)
    connections: list[ServiceConnection] = []

    # DEPENDS_ON edges from dependency manifests
    for pkg_name, target_repo in dep_map.items():
        connections.append(
            ServiceConnection(
                source=repo_name,
                target=target_repo,
                rel_type="DEPENDS_ON",
                properties={"package": pkg_name},
            )
        )

    # USES_CLIENT edges from code patterns
    connections.extend(detect_client_patterns(chunks, repo_name))

    # HTTP_CALLS edges from code patterns
    connections.extend(detect_http_patterns(chunks, repo_name))

    # Kafka topic usage
    topics = detect_kafka_patterns(chunks, repo_name)

    # API endpoints
    endpoints = detect_api_routes(chunks, repo_name)

    logger.info(
        "Service analysis for '%s': %d connections, %d endpoints, %d topics",
        repo_name,
        len(connections),
        len(endpoints),
        len(topics),
    )

    return ServiceAnalysis(
        repo_name=repo_name,
        dep_map=dep_map,
        connections=connections,
        endpoints=endpoints,
        topics=topics,
    )
