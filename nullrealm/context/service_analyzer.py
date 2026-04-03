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


# ---------------------------------------------------------------------------
# Federation indexing
# ---------------------------------------------------------------------------

ROLE_TO_SERVICE: dict[str, str] = {
    "s3": "cloudserver",
    "backbeat": "backbeat",
    "vault": "vault",
    "metadata": "MetaData",
    "bucketd": "MetaData",
    "dbd": "MetaData",
    "utapi": "utapi",
    "scuba": "scuba",
    "bucket-notifications": "backbeat",
    "s3-frontend": "s3-frontend",
    "s3-analytics-clickhouse": "s3-analytics-clickhouse",
    "s3-analytics-fluentbit": "s3-analytics-fluentbit",
    "log-courier": "log-courier",
    "redis": "redis",
    "local-redis": "redis",
    "sproxyd": "sproxyd",
    "identisee": "identisee",
    "nfsd": "nfsd",
    "osis": "osis",
    "sagentd": "sagentd",
    "s3-cdmi": "cloudserver",
    "scuba-bucketd": "scuba",
    "metadata-s3": "MetaData",
    "metadata-scuba": "MetaData",
    "metadata-vault": "MetaData",
    "metadata-migration": "MetaData",
    "backbeat-queue": "backbeat",
    "backbeat-worker-base": "backbeat",
    "object-repair": "s3utils",
}

# Regex patterns for topology extraction from Jinja2 config templates
_TOPOLOGY_PATTERNS: list[tuple[str, str, str]] = [
    (r'"bucketd"\s*:\s*\{[^}]*"host"', "bucketd", "HTTP_CALLS"),
    (r'"vaultd"\s*:\s*\{[^}]*"host"', "vault", "HTTP_CALLS"),
    (r'"zookeeper"\s*:\s*\{[^}]*"connectionString"', "zookeeper", "USES_INFRA"),
    (r'"kafka"\s*:\s*\{[^}]*"hosts"', "kafka", "USES_INFRA"),
    (r'"redis"', "redis", "USES_INFRA"),
    (r'"s3"\s*:\s*\{[^}]*"host"', "cloudserver", "HTTP_CALLS"),
]


def _detect_template_language(filename: str, content: str) -> str:
    """Detect language from a Jinja2 template filename."""
    name_lower = filename.lower()
    if name_lower.endswith(".sql.j2"):
        return "sql"
    if "nginx" in name_lower or "nginx" in content[:200].lower():
        return "nginx"
    if name_lower.endswith((".yml.j2", ".yaml.j2")):
        return "yaml"
    if name_lower.endswith(".json.j2"):
        return "json"
    return "jinja2"


def _split_large_template(text: str, max_lines: int = 200) -> list[str]:
    """Split a large template into logical sections.

    Splits at blank lines separating blocks, ``{%`` block boundaries,
    or ``---`` separators.
    """
    lines = text.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return [text]

    chunks: list[str] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()
        is_boundary = (
            stripped == ""
            or stripped.startswith("{%")
            or stripped == "---"
        )
        if is_boundary and len(current) >= max_lines // 2:
            chunks.append("".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        chunks.append("".join(current))

    return chunks


def _chunk_templates(federation_path: Path) -> list[CodeChunk]:
    """Walk ``roles/run-*/templates/*.j2`` and produce CodeChunks."""
    chunks: list[CodeChunk] = []
    roles_dir = federation_path / "roles"
    if not roles_dir.is_dir():
        return chunks

    for role_dir in sorted(roles_dir.glob("run-*")):
        templates_dir = role_dir / "templates"
        if not templates_dir.is_dir():
            continue

        role_name = role_dir.name.removeprefix("run-")
        service_name = ROLE_TO_SERVICE.get(role_name, role_name)

        for tpl_file in sorted(templates_dir.glob("*.j2")):
            try:
                content = tpl_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Strip .j2 suffix for the symbol name
            base_name = tpl_file.name
            if base_name.endswith(".j2"):
                base_name = base_name[:-3]
            symbol_name = f"{role_name}.{base_name}"
            language = _detect_template_language(tpl_file.name, content)
            rel_path = str(tpl_file.relative_to(federation_path))

            sections = _split_large_template(content)
            for i, section_text in enumerate(sections):
                chunk_symbol = symbol_name if len(sections) == 1 else f"{symbol_name}[{i}]"
                chunks.append(
                    CodeChunk(
                        text=section_text,
                        file_path=rel_path,
                        symbol_name=chunk_symbol,
                        symbol_type="config",
                        language=language,
                        metadata={"role": role_name, "service": service_name},
                    )
                )

    return chunks


def _chunk_group_vars(federation_path: Path) -> list[CodeChunk]:
    """Read ``group_vars/all`` and split into per-service default blocks."""
    chunks: list[CodeChunk] = []
    gv_path = federation_path / "group_vars" / "all"
    if not gv_path.exists():
        return chunks

    try:
        content = gv_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return chunks

    file_path = "group_vars/all"

    # Split into top-level blocks. We look for lines matching
    # ``defaults.XXXX:`` at the start (possibly indented by exactly 0 or 2
    # spaces) as block headers.  Also capture docker image and port sections.
    current_name: str | None = None
    current_lines: list[str] = []
    block_re = re.compile(r"^(\s{0,2})(defaults\.(\w[\w.-]*))\s*:")
    docker_re = re.compile(r"^(\s{0,2})(docker_images|images)\s*:", re.IGNORECASE)
    port_re = re.compile(r"^(\s{0,2})(ports|port_defaults)\s*:", re.IGNORECASE)

    def _flush() -> None:
        if current_name and current_lines:
            chunks.append(
                CodeChunk(
                    text="".join(current_lines),
                    file_path=file_path,
                    symbol_name=current_name,
                    symbol_type="config",
                    language="yaml",
                )
            )

    for line in content.splitlines(keepends=True):
        m_block = block_re.match(line)
        m_docker = docker_re.match(line)
        m_port = port_re.match(line)

        if m_block:
            _flush()
            current_name = m_block.group(2)
            current_lines = [line]
        elif m_docker:
            _flush()
            current_name = "docker_images"
            current_lines = [line]
        elif m_port:
            _flush()
            current_name = "port_definitions"
            current_lines = [line]
        else:
            current_lines.append(line)

    _flush()
    return chunks


def _chunk_documentation(federation_path: Path) -> list[CodeChunk]:
    """Read ``.md`` files from ``documentation/``, ``Components.md``, and ``Developing.md``.

    Each ``##`` section becomes its own chunk.
    """
    chunks: list[CodeChunk] = []
    md_files: list[Path] = []

    docs_dir = federation_path / "documentation"
    if docs_dir.is_dir():
        md_files.extend(sorted(docs_dir.glob("*.md")))

    for name in ("Components.md", "Developing.md"):
        candidate = federation_path / name
        if candidate.is_file():
            md_files.append(candidate)

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        base = md_file.stem
        rel_path = str(md_file.relative_to(federation_path))

        # Split by ## headers
        sections: list[tuple[str, str]] = []  # (title, body)
        current_title = "intro"
        current_lines: list[str] = []

        for line in content.splitlines(keepends=True):
            if line.startswith("## "):
                if current_lines:
                    sections.append((current_title, "".join(current_lines)))
                current_title = line.lstrip("# ").strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_title, "".join(current_lines)))

        for title, body in sections:
            if not body.strip():
                continue
            chunks.append(
                CodeChunk(
                    text=body,
                    file_path=rel_path,
                    symbol_name=f"doc.{base}.{title}",
                    symbol_type="documentation",
                    language="markdown",
                )
            )

    return chunks


def _chunk_tooling_playbooks(federation_path: Path) -> list[CodeChunk]:
    """Read ``tooling-playbooks/*.yml`` — one chunk per file."""
    chunks: list[CodeChunk] = []
    playbooks_dir = federation_path / "tooling-playbooks"
    if not playbooks_dir.is_dir():
        return chunks

    for yml_file in sorted(playbooks_dir.glob("*.yml")):
        try:
            content = yml_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        chunks.append(
            CodeChunk(
                text=content,
                file_path=str(yml_file.relative_to(federation_path)),
                symbol_name=f"playbook.{yml_file.stem}",
                symbol_type="playbook",
                language="yaml",
            )
        )

    return chunks


def _extract_topology_from_configs(
    federation_path: Path,
) -> list[ServiceConnection]:
    """Parse ``roles/run-*/templates/config.json.j2`` for service connections."""
    connections: list[ServiceConnection] = []
    seen: set[tuple[str, str, str]] = set()
    roles_dir = federation_path / "roles"
    if not roles_dir.is_dir():
        return connections

    for role_dir in sorted(roles_dir.glob("run-*")):
        config_file = role_dir / "templates" / "config.json.j2"
        if not config_file.is_file():
            continue

        role_name = role_dir.name.removeprefix("run-")
        source = ROLE_TO_SERVICE.get(role_name, role_name)

        try:
            text = config_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for pattern, target, rel_type in _TOPOLOGY_PATTERNS:
            if re.search(pattern, text):
                key = (source, target, rel_type)
                if key not in seen:
                    seen.add(key)
                    connections.append(
                        ServiceConnection(
                            source=source,
                            target=target,
                            rel_type=rel_type,
                            properties={"detected_in": str(config_file.relative_to(federation_path))},
                        )
                    )

    return connections


def index_federation(
    federation_path: Path,
) -> tuple[list[CodeChunk], list[ServiceConnection]]:
    """Index Federation deployment configs, docs, and playbooks.

    Returns:
        (chunks for pgvector embedding, service connections for Neo4j topology)
    """
    template_chunks = _chunk_templates(federation_path)
    group_var_chunks = _chunk_group_vars(federation_path)
    doc_chunks = _chunk_documentation(federation_path)
    playbook_chunks = _chunk_tooling_playbooks(federation_path)

    all_chunks = template_chunks + group_var_chunks + doc_chunks + playbook_chunks

    connections = _extract_topology_from_configs(federation_path)

    logger.info(
        "Federation index: Found %d templates, %d group_vars sections, "
        "%d docs, %d playbooks",
        len(template_chunks),
        len(group_var_chunks),
        len(doc_chunks),
        len(playbook_chunks),
    )

    return all_chunks, connections
