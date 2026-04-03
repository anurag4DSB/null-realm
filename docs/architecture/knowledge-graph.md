# Multi-Repo Knowledge Graph

Specification for the null-realm knowledge graph that models the Scality S3 platform as a connected system of services, code symbols, infrastructure, and data flows. This document is the authoritative reference for the graph data model. Review and modify here before writing code.

---

## 1. The Scality S3 Platform Ecosystem

The platform is a microservice architecture built primarily in JavaScript/Node.js. Twelve repositories (six open-source, six closed-source) form a layered system: API servers, shared libraries, client libraries, async processors, and deployment orchestration.

| Repo | Visibility | Language | Role |
|------|-----------|----------|------|
| cloudserver | Open | JS | S3 API server -- handles all S3 operations (PUT, GET, DELETE, List, etc.). The external entry point for all client requests. |
| Arsenal | Open | JS/TS | Shared library -- metadata backends, data backends, auth helpers, error definitions, S3 models, middleware. Used by nearly every other repo. |
| backbeat | Open | JS | Async operations engine -- cross-region replication (CRR), lifecycle expiration, bucket notifications, ingestion. Organized as extensions with independent queue processors. |
| Vault | Closed | JS | Authentication / IAM service -- user and account management, S3 signature verification, STS (Security Token Service). |
| MetaData | Closed | JS | Metadata daemon (bucketd) -- stores bucket and object metadata, runs raft consensus for consistency. |
| vaultclient | Open | JS | HTTP client library for Vault -- defines the auth API contract. Imported by any service that needs to authenticate requests. |
| bucketclient | Open | JS | HTTP client library for MetaData/bucketd -- defines the metadata API contract. |
| utapi | Open | JS | Utilization and metrics service -- tracks storage usage per account and per bucket. |
| scuba (SUR in Federation) | Open | JS | Quota and utilization enforcement service. Known as "SUR" (Scality Usage Reports) in Federation deployments. |
| scubaclient | Open | JS | HTTP client library for scuba/SUR -- quota enforcement API contract. |
| sproxydclient | Open | JS | HTTP client library for sproxyd -- object data storage API contract. |
| Federation | Closed | Ansible | Deployment orchestrator -- Ansible playbooks that define how all services are deployed, configured, and connected. The single source of truth for service topology, ports, and connection parameters. |

### Key architectural patterns

- **Client library convention**: Each internal service has a corresponding `*client` package (vaultclient, bucketclient, scubaclient, sproxydclient). Services never make raw HTTP calls to each other; they import the client library. This means `require('vaultclient')` in code is a reliable signal of a service-to-service dependency.

- **Arsenal as shared core**: Arsenal is imported by nearly every repo. It contains the metadata wrapper (`MetadataWrapper`), data wrappers, error definitions, auth utilities, and S3 models. Cross-repo analysis must handle Arsenal as the central node in the dependency graph.

- **Federation as topology oracle**: Federation's Ansible templates (`roles/run-*/templates/config.json.j2`) define every service connection at deployment time. When code analysis is ambiguous, Federation is the ground truth for what talks to what.

---

## 2. Service Topology

The complete service-to-service communication map, derived from Federation config templates and code analysis.

```
cloudserver  --> bucketd          (metadata reads/writes)
             --> vault            (request authentication, signature verification)
             --> backbeat         (HTTP proxy for CRR status, lifecycle, notifications)
             --> redis            (session cache, metadata cache)
             --> utapi            (storage metrics reporting)

backbeat     --> bucketd          (queue populator reads metadata changelog)
             --> kafka            (event queues for all extensions)
             --> s3/cloudserver   (internal S3 operations for replication)
             --> vault            (authentication for internal operations)
             --> zookeeper        (distributed coordination, leader election)

vault        --> redis            (session storage, token cache)
             --> scuba            (quota enforcement checks)
             --> sproxyd          (data storage for account metadata)

utapi        --> bucketd          (metadata queries for usage calculation)
             --> redis            (metrics cache, rate limiting)
             --> s3/cloudserver   (internal S3 access)
             --> vault            (authentication)
             --> warp10           (time-series storage for usage metrics)

bucket-notif --> bucketd          (reads notification configurations)
             --> kafka            (publishes notification events)
             --> zookeeper        (coordination)

identisee    --> s3/cloudserver   (S3 access)
             --> scuba            (quota checks)
             --> utapi            (usage queries)
             --> vault            (authentication)

scuba        --> bucketd          (quota metadata queries)
```

---

## 3. Port Registry

Extracted from Federation's `group_vars/all`. These are the default ports; Federation templates can override per environment.

| Service | Port | Purpose | Protocol |
|---------|------|---------|----------|
| cloudserver | 8000 | S3 API (external) | HTTP |
| cloudserver | 8003 | Internal API (health, metrics) | HTTP |
| cloudserver | 8002 | Prometheus metrics | HTTP |
| vault | 8500 | IAM API (service) | HTTP |
| vault | 8600 | Admin API | HTTP |
| vault | 8650 | STS (Security Token Service) | HTTP |
| bucketd | 9000 | Metadata API | HTTP |
| backbeat | 7200-7900 | Queue processors (varies by extension) | HTTP |
| utapi | 8100 | Utilization API | HTTP |
| redis | 6379 | Cache / sessions | TCP |
| kafka | 9092 | Event broker | TCP |
| zookeeper | 2181 | Coordination | TCP |
| sproxyd | 7084-7085 | Object data storage | HTTP |
| scuba | 9190 | Quota monitoring | HTTP |
| warp10 | 4802 | Time-series database | HTTP |

---

## 4. Dependency Graph

npm dependencies with `github.com/scality/` URLs, extracted from each repo's `package.json`. This is the highest-confidence signal for cross-repo relationships.

```
cloudserver    --> arsenal, bucketclient, scubaclient, utapi, vaultclient, werelogs
backbeat       --> arsenal, bucketclient, cloudserver, vaultclient, werelogs, breakbeat
Vault          --> arsenal, MetaData, scubaclient, sproxydclient, utapi, vaultclient, werelogs
MetaData       --> arsenal, bucketclient, sproxydclient, werelogs
utapi          --> arsenal, bucketclient, vaultclient, werelogs
scuba          --> arsenal, bucketclient, vaultclient, werelogs
bucketclient   --> arsenal, httpagent, werelogs
vaultclient    --> httpagent, werelogs
sproxydclient  --> httpagent, werelogs
```

Arsenal appears in every service's dependency list. werelogs (structured logging) is similarly universal. Both are shared libraries, not services, but the graph must represent them because code symbols flow through them.

---

## 5. Neo4j Data Model

### Node Types

```
:Symbol
  -- A code-level symbol: function, class, method, module.
  -- Properties:
       file     : str   -- Relative file path within the repo (e.g., "lib/api/objectPut.js")
       name     : str   -- Symbol name (e.g., "objectPut", "MetadataWrapper.putObjectMD")
       repo     : str   -- Repository name (e.g., "cloudserver")
       type     : str   -- "function", "class", "module", "method"
       language : str   -- "javascript", "python", "go", "typescript"
  -- Examples:
       {file: "lib/api/objectPut.js", name: "objectPut", repo: "cloudserver", type: "function", language: "javascript"}
       {file: "lib/metadata/MetadataWrapper.js", name: "MetadataWrapper", repo: "Arsenal", type: "class", language: "javascript"}

:Service
  -- A deployable microservice or library.
  -- Properties:
       name        : str   -- Short name (e.g., "cloudserver", "vault", "arsenal")
       repo        : str   -- Repository name (may differ from service name)
       port        : int   -- Primary service port (0 for libraries)
       protocol    : str   -- "HTTP", "TCP", or "" for libraries
       description : str   -- Brief description of the service role
  -- Examples:
       {name: "cloudserver", repo: "cloudserver", port: 8000, protocol: "HTTP", description: "S3 API server"}
       {name: "bucketd", repo: "MetaData", port: 9000, protocol: "HTTP", description: "Metadata daemon"}

:Endpoint
  -- An HTTP API route exposed by a service.
  -- Properties:
       path        : str   -- URL path (e.g., "/_/crr/metrics/all")
       method      : str   -- HTTP method (e.g., "GET", "POST")
       service     : str   -- Service that exposes this endpoint
       description : str   -- What the endpoint does
  -- Examples:
       {path: "/_/crr/pause", method: "POST", service: "backbeat", description: "Pause CRR for a site"}
       {path: "/_/crr/metrics/all", method: "GET", service: "backbeat", description: "CRR replication metrics"}

:Topic
  -- A Kafka topic used for async communication.
  -- Properties:
       name        : str   -- Topic name (e.g., "backbeat-replication")
       description : str   -- Purpose of the topic
  -- Examples:
       {name: "backbeat-replication", description: "CRR replication queue"}
       {name: "backbeat-replication-status", description: "CRR status updates"}

:InfraService
  -- An infrastructure dependency that is not Scality code.
  -- Properties:
       name : str   -- Service name (e.g., "redis", "kafka")
       type : str   -- Category: "cache", "event-bus", "coordination", "time-series", "search"
  -- Examples:
       {name: "redis", type: "cache"}
       {name: "kafka", type: "event-bus"}
       {name: "zookeeper", type: "coordination"}
       {name: "warp10", type: "time-series"}
```

### Relationship Types

```
--- Service-level relationships ---

:DEPENDS_ON
  Direction : Service --> Service
  Meaning   : Library dependency (from package.json)
  Properties: {package: str}
  Example   : (cloudserver)-[:DEPENDS_ON {package: "arsenal"}]->(arsenal)

:HTTP_CALLS
  Direction : Service --> Service
  Meaning   : HTTP communication at runtime (from Federation config + code patterns)
  Properties: {port: int, purpose: str}
  Example   : (cloudserver)-[:HTTP_CALLS {port: 9000, purpose: "metadata"}]->(bucketd)

:USES_CLIENT
  Direction : Service --> Service
  Meaning   : Communicates via a Scality client library
  Properties: {via: str}
  Example   : (cloudserver)-[:USES_CLIENT {via: "vaultclient"}]->(vault)

:EXPOSES
  Direction : Service --> Endpoint
  Meaning   : API routes the service defines
  Example   : (backbeat)-[:EXPOSES]->({path: "/_/crr/pause", method: "POST"})

:PRODUCES
  Direction : Service --> Topic
  Meaning   : Kafka producer relationship
  Example   : (backbeat)-[:PRODUCES]->({name: "backbeat-replication"})

:CONSUMES
  Direction : Service --> Topic
  Meaning   : Kafka consumer relationship
  Example   : (backbeat)-[:CONSUMES]->({name: "backbeat-replication"})

:USES_INFRA
  Direction : Service --> InfraService
  Meaning   : Infrastructure dependency
  Properties: {purpose: str}
  Example   : (cloudserver)-[:USES_INFRA {purpose: "cache"}]->(redis)


--- Code-level relationships ---

:RELATES
  Direction : Symbol --> Symbol
  Meaning   : Intra-repo code relationship (within the same repository)
  Properties: {type: str}
  type values: "CALLS", "IMPORTS", "INHERITS", "CONTAINS"
  Example   : (objectPut)-[:RELATES {type: "CALLS"}]->(MetadataWrapper.putObjectMD)

:XREF
  Direction : Symbol --> Symbol
  Meaning   : Cross-repo code reference (symbol in repo A calls symbol in repo B)
  Properties: {type: str, package: str}
  type values: "CALLS", "IMPORTS"
  Example   : (objectPut {repo: "cloudserver"})-[:XREF {type: "CALLS", package: "arsenal"}]->(MetadataWrapper.putObjectMD {repo: "Arsenal"})


--- Linking relationships ---

:BELONGS_TO
  Direction : Symbol --> Service
  Meaning   : Symbol is defined within this service's repository
  Example   : (objectPut {repo: "cloudserver"})-[:BELONGS_TO]->(cloudserver:Service)
```

### Schema Summary Diagram

```
                          :DEPENDS_ON
              :Service ──────────────────> :Service
                │  │                          │
                │  │ :HTTP_CALLS              │
                │  │ :USES_CLIENT             │
                │  └──────────────────────────┘
                │
                ├──:EXPOSES──────> :Endpoint
                ├──:PRODUCES─────> :Topic
                ├──:CONSUMES─────> :Topic
                └──:USES_INFRA───> :InfraService

              :Symbol ──:RELATES──> :Symbol  (intra-repo)
              :Symbol ──:XREF────> :Symbol   (cross-repo)
              :Symbol ──:BELONGS_TO──> :Service
```

---

## 6. Cross-Repo Resolution Strategy

Cross-repo linking is the hard problem. A function in cloudserver calls `MetadataWrapper.putObjectMD()`, which is defined in Arsenal. The graph must connect them. We use a four-layer approach, ordered by confidence.

### Layer 1: package.json resolution (highest confidence)

Parse `dependencies` from each repo's `package.json`. Match Scality dependencies by the `github.com/scality/` URL pattern. Create `DEPENDS_ON` edges between Service nodes.

This layer also scopes all subsequent resolution: if cloudserver does not list Arsenal in its `package.json`, we do not attempt to create XREF edges between their symbols.

```
package.json → dep_map = {"cloudserver": ["arsenal", "vaultclient", "bucketclient", ...]}
             → CREATE (cloudserver)-[:DEPENDS_ON]->(arsenal)
             → CREATE (cloudserver)-[:DEPENDS_ON]->(vaultclient)
```

### Layer 2: Symbol name matching (scoped to known deps)

For each repo, look at symbols that have outgoing CALLS relationships with unresolved targets (target_file is empty). Search the dependency repos' symbol tables for name matches. Create XREF edges with package context.

This is scoped: cloudserver symbols only match against Arsenal, vaultclient, bucketclient, etc. (its known dependencies). This prevents false positives from common names like `get`, `create`, `delete`.

```
-- cloudserver calls MetadataWrapper.putObjectMD
-- Arsenal defines MetadataWrapper.putObjectMD
-- cloudserver depends on arsenal (from package.json)
→ CREATE (objectPut {repo: "cloudserver"})-[:XREF {type: "CALLS", package: "arsenal"}]->(MetadataWrapper.putObjectMD {repo: "Arsenal"})
```

### Layer 3: Federation config extraction

Parse Federation's Ansible templates for authoritative service topology:

1. `group_vars/all` -- service definitions (images, ports, default config)
2. `roles/run-*/templates/config.json.j2` -- connection parameters (hosts, ports, endpoints)
3. Output: Service nodes, InfraService nodes, HTTP_CALLS edges, USES_INFRA edges, port registry

Federation is the ground truth for deployment topology. When code analysis suggests a connection that Federation doesn't confirm, the code analysis is suspect (could be dead code, test code, or conditional logic).

### Layer 4: Code pattern detection

Known patterns in the Scality codebase that indicate service-to-service communication:

| Pattern | Signal | Edge Type |
|---------|--------|-----------|
| `require('vaultclient')` + `new Client(...)` | Auth calls to Vault | USES_CLIENT |
| `require('bucketclient')` + `new RESTClient(...)` | Metadata calls to bucketd | USES_CLIENT |
| `httpProxy.createProxyServer(...)` | HTTP proxy (cloudserver to backbeat) | HTTP_CALLS |
| `new BackbeatProducer(...)` | Kafka producer | PRODUCES |
| `new BackbeatConsumer(...)` | Kafka consumer | CONSUMES |
| `require('scubaclient')` | Quota enforcement calls | USES_CLIENT |
| `require('sproxydclient')` | Data storage calls | USES_CLIENT |

---

## 7. Backbeat Feature Extensions

Backbeat organizes its functionality as extensions, each with an independent queue processor, its own Kafka topics, and (usually) its own API endpoints. Understanding backbeat requires knowing the extension model.

| Extension | Purpose | Kafka Topics | API Endpoints |
|-----------|---------|-------------|---------------|
| replication | Cross-region replication (CRR) | `backbeat-replication`, `backbeat-replication-status`, `backbeat-replication-failed` | `/_/crr/pause`, `/_/crr/resume`, `/_/crr/metrics`, `/_/crr/metrics/all` |
| lifecycle | Object lifecycle expiration | `lifecycle-queue` | `/_/lifecycle/*` |
| notification | Bucket event notifications | Configurable per destination (one topic per notification target) | (via queue populator, no direct API) |
| ingestion | Source bucket ingestion from external S3 | `ingestion-queue` | `/_/ingestion/status`, `/_/ingestion/schedule` |

Each extension has a queue populator (reads from bucketd's metadata changelog and pushes events to Kafka) and a queue processor (consumes from Kafka and executes the operation). The queue populator is shared across extensions; each queue processor runs as a separate process with its own port in the 7200-7900 range.

---

## 8. Example Queries

Practical Cypher queries that the knowledge graph enables. These are the primary use cases for the graph and inform the data model design.

```cypher
-- "What would bucket notifications as a service need to integrate with?"
MATCH (s:Service {name: "bucket-notifications"})-[r]->(target)
RETURN s.name AS source, type(r) AS relationship, target.name AS target

-- "How does cloudserver authenticate requests?"
MATCH path = (cs:Service {name: "cloudserver"})-[:USES_CLIENT|HTTP_CALLS*1..2]-(v:Service {name: "vault"})
RETURN path

-- "What handles PUT object end-to-end?"
MATCH (sym:Symbol {name: "objectPut"})-[:XREF|RELATES*1..4]-(related)
WHERE related.file <> ""
RETURN sym.repo, sym.name, related.repo, related.name, related.file

-- "Which services would be affected if bucketd goes down?"
MATCH (s:Service)-[:HTTP_CALLS|USES_CLIENT|DEPENDS_ON*1..2]->(b:Service {name: "bucketd"})
RETURN DISTINCT s.name

-- "What Kafka topics does backbeat use?"
MATCH (bb:Service {name: "backbeat"})-[r:PRODUCES|CONSUMES]->(t:Topic)
RETURN t.name, type(r) AS role

-- "What shared Arsenal symbols does cloudserver use that backbeat also uses?"
MATCH (cs:Symbol {repo: "cloudserver"})-[:XREF]->(shared:Symbol {repo: "Arsenal"})
MATCH (bb:Symbol {repo: "backbeat"})-[:XREF]->(shared)
RETURN DISTINCT shared.name, shared.file

-- "What infrastructure does cloudserver depend on?"
MATCH (cs:Service {name: "cloudserver"})-[:USES_INFRA]->(infra:InfraService)
RETURN infra.name, infra.type

-- "What endpoints does backbeat expose for CRR?"
MATCH (bb:Service {name: "backbeat"})-[:EXPOSES]->(ep:Endpoint)
WHERE ep.path CONTAINS "crr"
RETURN ep.path, ep.method, ep.description

-- "Full dependency chain from cloudserver to sproxyd (data storage)"
MATCH path = shortestPath(
  (cs:Service {name: "cloudserver"})-[:HTTP_CALLS|USES_CLIENT|DEPENDS_ON*]->(sp:InfraService {name: "sproxyd"})
)
RETURN path
```

---

## 9. How to Add a New Repo

Step-by-step guide for adding a repository to the knowledge graph.

### Step 1: Register

```
add_repo(url="https://github.com/scality/vaultclient", branch="development/7.70", auth_type="public")
```

Creates a row in the `repos` table with `status=pending`. For private repos (Vault, MetaData, Federation), set `auth_type="token"` -- the indexer will use the `GITHUB_TOKEN` environment variable.

### Step 2: Index

```
index_repo(url="https://github.com/scality/vaultclient", branch="development/7.70", auth_type="public")
```

Submits an Argo workflow that:
1. Clones the repo (shallow, `--depth 1`)
2. Parses all source files via language-specific parsers (Python AST, tree-sitter for JS/TS/Go)
3. Extracts CodeChunks (functions, classes, modules) and CodeRelationships (CALLS, IMPORTS, INHERITS, CONTAINS)
4. Embeds chunks via LiteLLM/Vertex AI `text-embedding-005` (768-dim)
5. Stores embeddings in pgvector (`code_embeddings` table)
6. Stores relationships in Neo4j (Symbol nodes + RELATES edges)
7. Generates `REPO_INDEX.md` summary

### Step 3: Link cross-repo

```
link_repos()
```

Re-runs the cross-repo linking pipeline across all indexed repos:
1. Reads `package.json` from each repo to build the dependency map
2. Creates `DEPENDS_ON` edges between Service nodes
3. Matches unresolved CALLS targets against dependency repo symbols
4. Creates `XREF` edges for confirmed matches
5. Runs code pattern detection for USES_CLIENT, PRODUCES, CONSUMES edges

### Step 4: Verify

```
list_repos()                        -- Confirm status is "ready"
code_search("relevant query")       -- Semantic search across the new repo
graph_query("SomeSymbol", depth=2)  -- Check graph connectivity
service_topology()                  -- Confirm service appears in topology
```

### Authentication for private repos

Private Scality repos (Vault, MetaData, Federation) require a GitHub personal access token:

1. Set `GITHUB_TOKEN` in the worker pod's environment (via K8s Secret `github-token`)
2. Use `auth_type="token"` when calling `add_repo` or `index_repo`
3. The clone URL is rewritten to `https://<token>@github.com/scality/<repo>`

---

## 10. How to Update the Data Model

If you need to add a new node type, relationship type, or property:

1. **Update this document** (`docs/architecture/knowledge-graph.md`). Define the new type with its properties, direction, and examples. Get the spec reviewed before writing code.

2. **Update `nullrealm/context/neo4j_store.py`**. Add new MERGE/query methods for the new type. Follow the existing pattern: batch UNWIND for writes, parameterized queries for reads.

3. **Update `nullrealm/context/service_analyzer.py`** if the new type requires a new detection pattern (e.g., a new code pattern or a new config file to parse).

4. **Update MCP tools** in `nullrealm/mcp_server.py` and `nullrealm/mcp_tools.py` if the new type requires new query capabilities exposed to users.

5. **Run `link_repos()`** to rebuild cross-repo edges with the updated model.

6. **Update the Grafana dashboard** if the new type should be visible in the knowledge graph metrics panel.

### Constraints

- **Neo4j Community Edition**: No role-based access control, no clustering. Single instance is sufficient for this use case (tens of thousands of nodes, not millions).
- **Merge semantics**: All node creation uses `MERGE` (not `CREATE`) to ensure idempotency on re-indexing.
- **Repo-scoped deletion**: Deleting a repo's data uses `MATCH (n:Symbol {repo: $repo}) DETACH DELETE n`. New node types (Service, Endpoint, Topic, InfraService) need equivalent scoped deletion.

---

## 11. Current State vs. Target State

### Current state (Phase 05 complete)

- **Node types**: Symbol only
- **Relationship types**: RELATES (with type property: CALLS, IMPORTS, INHERITS, CONTAINS)
- **Indexed repos**: null-realm (self), cloudserver, Arsenal, backbeat
- **Cross-repo**: No XREF edges. Each repo's graph is isolated.
- **Service topology**: Not modeled. No Service, Endpoint, Topic, or InfraService nodes.

### Target state (Phase 05-05)

- **Node types**: Symbol, Service, Endpoint, Topic, InfraService
- **Relationship types**: All types listed in Section 5
- **Indexed repos**: All 12 repos (including private via GITHUB_TOKEN)
- **Cross-repo**: XREF edges connecting symbols across repos, scoped by package.json
- **Service topology**: Full topology from Federation config extraction

### Implementation order

| Step | Description | Depends on |
|------|-------------|------------|
| 1 | This document + ADR-011 | -- |
| 2 | `service_analyzer.py` (package.json parser, code pattern detector) | Step 1 |
| 3 | Neo4j store extensions (new node types, XREF, service queries) | Step 2 |
| 4 | Wire into indexing pipeline | Steps 2-3 |
| 5 | New MCP tools (link_repos, service_topology, service_deps) | Steps 3-4 |
| 6 | Index remaining repos (private + open) | Steps 4-5 |
| 7 | Federation topology extraction | Step 5 |
| 8 | Deploy, test, verify | Steps 6-7 |
