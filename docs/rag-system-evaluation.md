# Hopocalypse RAG — Evaluation, Failure Modes & Research Readiness

System under analysis: the `hopocalypse` MCP server serving a hybrid pgvector + Neo4j retrieval stack over 16 indexed Scality repos (Arsenal, backbeat, bucketclient, cloudserver, Federation, identisee, log-courier, MetaData, metadata-migration, s3utils, scuba, scubaclient, sproxydclient, utapi, vault, vaultclient). Total ~12.9k chunks, ~2.0k files. Default tool argument `repo="null-realm"` points at a repo that is **not** indexed.

## 1. Real Query Examples (30)

**Lexical / exact lookup**
1. `find function _checkBackendVersioningImplemented`
2. `where is KafkaBacklogMetrics defined`
3. `class RepdServer`
4. `grep isOkPolicyDocument across repos`
5. `show file cloudserver/lib/api/bucketPutVersioning.js`
6. `find all callers of checkPolicies`

**Semantic search**
7. `how does bucket versioning enablement work`
8. `IAM policy evaluation and implicit deny`
9. `multipart upload part number validation`
10. `consumer backpressure and lag tracking in backbeat`
11. `how are CORS headers collected for a bucket op`
12. `rate limiting / quota enforcement`
13. `where is metadata written to the raft log`
14. `replication retry on 5xx from s3`

**Graph / structural reasoning**
15. `who imports vaultclient`
16. `shortest call-path from objectPutPart to metadata write`
17. `symbols that CALL embed_texts`
18. `list services that DEPENDS_ON vault`
19. `Kafka topics produced by backbeat`
20. `show cross-repo XREFs for bucketclient`

**Debugging / incident analysis**
21. `why would a multipart complete succeed but versionId be missing`
22. `stuck raft follower — what triggers replicatePendingEntries`
23. `which code path logs "slow task"`
24. `where does backbeat decide a consumer is unhealthy`
25. `what code runs when vault returns AccessDenied with implicit=true`
26. `why is getBucketVersioning returning 200 with empty body`

**Design / architecture**
27. `how does cloudserver authenticate an S3 request end-to-end`
28. `what is the replication pipeline from cloudserver → backbeat → remote site`
29. `architecture of metadata-migration vs MetaData`
30. `how are Federation Jinja templates rendered into deployed configs`

## 2. Retrieval Traces (10 real calls against hopocalypse)

Similarity = `1 - cosine_distance`; top-k default 10. No reranking; `repo` is the only filter. All runs below are vector-only (no graph expansion) unless noted.

| # | Query | Tool | Repo | Top-1 hit (score) | Graph expansion |
|---|---|---|---|---|---|
| 1 | `bucket versioning enabled check` | `code_search` | cloudserver | `bucketPutVersioning.js:_checkBackendVersioningImplemented` **0.809** | no |
| 2 | `IAM policy evaluation decision` | `code_search` | vault | `lib/Check.js:isOkPolicyDocument` **0.593** (weak; `checkPolicies` only #2 at 0.584) | no |
| 3 | `multipart upload part number validation` | `code_search` | cloudserver | `objectPutPart.js:_getPartKey` **0.715** (4/5 hits are tests, not prod path) | no |
| 4 | `Kafka consumer lag backpressure` | `code_search` | backbeat | `BackbeatConsumer._startProcessingTask` **0.727** | no |
| 5 | `metadata raft leader election` | `code_search` | MetaData | `tests/.../leader-election/test.js:findLeader` **0.704** (test file outranks `RaftSession.receiveVote` at 0.649) | no |
| 6 | `hnsw vector index creation` | `code_search` | (default) null-realm | **0 results** (repo not indexed) | no |
| 7 | `OAuth token validation JWT` | `code_search` | (default) null-realm | **0 results** (repo not indexed) | no |
| 8 | `neighbors of embed_texts` | `graph_query` depth=2 | — | 49 neighbors returned; ~30 are Python built-ins (`:len`, `:any`, `:sorted`, `:append`, `:where`) with no file path | n/a |
| 9 | `list_repos` | metadata | — | 16 repos ready, 12.9k chunks total; oldest `last_indexed_at` = 2026-04-07 (16 days stale) | n/a |
| 10 | `service_deps("cloudserver")` | `service_deps` | — | **runtime error**: `'list' object has no attribute 'items'` | n/a |

Assembled context shape (from `context_assemble`): `REPO_INDEX.md[:2000]` + top-5 vector snippets (each truncated to 500 chars) + up to 10 Neo4j 1-hop neighbors of the top-3, concatenated as markdown. No dedup, no MMR, no token budgeter — estimate only as `chars/4`.

## 3. Embedding Input Examples

The indexer builds `texts = [c.text for c in all_chunks]` (`indexer.py:347`). **The raw source of the symbol is the only thing embedded.** `file_path`, `symbol_name`, `language`, `docstring`, `repo` live in metadata columns but are **not** in the embedding string. Storage truncates at 10 KB *after* embedding. Representative inputs (verbatim, minus ellipsis):

1. **Python function** — `def embed_texts(texts: list[str]) -> np.ndarray:\n    """Embed a batch...\n    if _use_vertex_ai(): return _embed_vertex(texts)\n    return _embed_local(texts)`
2. **Python class** — full class source of `PgVectorStore` from `class PgVectorStore:` through the last method.
3. **JS function (Node/CommonJS)** — `function _checkBackendVersioningImplemented(bucket) { const bucketLocation = bucket.getLocationConstraint(); ... return true; }`
4. **JS arrow** — `(req, res, next) => { ... }` body, no surrounding `const handler =`.
5. **TS method** — method body lifted from its class; parent class only in `metadata.class`.
6. **TS interface** — `interface IamPolicyDoc { Version: string; Statement: Statement[]; }` (tagged `kind: "interface"`).
7. **Go function with receiver** — `func (s *RepdServer) onElectedLeader(evt Event) { ... }` (`receiver_type="*RepdServer"`).
8. **Go struct** — `type BackbeatConsumer struct { ... }`.
9. **Module docstring (Python)** — the bare triple-quoted string of `nullrealm/mcp_tools.py`.
10. **Federation Jinja template block** — a single block from a `.j2` file (Federation-only extension); config templates are indexed despite absence from code-language set.

Consequences: identifier-only queries ("`isOkPolicyDocument`") compete with semantically similar functions in the same file; no symbol name, path, or language bias in the vector. Long functions (>8 KB) get embedded in full with no summarization.

## 4. Failure Modes (observed & latent)

- **Exact identifier misses.** Query #2 (`IAM policy evaluation`) returned a validator (`isOkPolicyDocument`, 0.593) above `checkPolicies` (0.584). No keyword/BM25 fallback and no identifier boost.
- **Test / prod conflation.** Query #5 — a `tests/.../leader-election/test.js` helper scored 0.704, above the real `RaftSession.receiveVote` (0.649). Tests make up a large share of top-5 for #3 and #5.
- **Near-duplicate crowding.** `putParts`, `getPartParams`, `enableVersioning` appear twice across test files and dominate top-5 because MMR is off.
- **Wrong-default footgun.** `code_search` defaults `repo="null-realm"`, but `null-realm` itself is **not** indexed → silent 0-result responses for perfectly reasonable queries (traces #6, #7). This is the single biggest usability bug.
- **Graph noise.** `graph_query("embed_texts", 2)` returns Python built-ins and bare attribute names (`:info`, `:where`, `:len`, `:append`) as nodes with `file="unknown"`. Call extraction treats any `Call` node identifier as a symbol.
- **Runtime bug.** `service_deps("cloudserver")` throws `'list' object has no attribute 'items'` — Cypher result shape mismatch; trace #10. No e2e test caught it.
- **Missing non-code context.** Most repos index only code; only Federation indexes Jinja/YAML/nginx/markdown. README, SQL migrations, Helm, Terraform, diagrams, incident docs are invisible.
- **Stale / mixed index.** 12/16 repos last indexed 2026-04-07 (16 days ago, branches like `development/8.3` may have moved). No commit SHA pinned per-index, so hits reference lines that may no longer exist on HEAD.
- **Truncation loss.** Chunks >10 KB get stored truncated; assembled context keeps only 500 chars/hit → surrounding control flow of large functions is lost by the time the agent sees it.

## 5. Current Evaluation

A benchmark directory exists (`benchmark/queries/`, untracked) with a `MANIFEST.md` and **one** annotated query `q0001.md` (archetype: architecture-exploration, commit-pinned to Federation `124134447e…`, with required/useful chunk labels and distractor roles). There is **no runnable harness**, no metric code (recall@k / MRR / nDCG not computed), no test corpus, no automated regression. Scoring criteria are described in prose only. The `/nullrealm-capture` skill captures queries during chat sessions but does not score them. **Effectively: no live evaluation.**

## 6. Observability

- **Prometheus** (2 metrics): `mcp_tool_calls_total{tool,user,status}`, `mcp_tool_duration_seconds{tool}` (8 buckets). **No** metrics for indexing duration, embedding latency, top-k score distribution, candidate count, token size.
- **OTEL spans** (`mcp-tools` tracer, `mcp.tool.{name}`, OpenInference attrs) fan out to Jaeger (gRPC) and Phoenix (HTTP). Captures input JSON, user, output first-500-chars, status — but **not** per-hit scores, embedding time, or graph hops.
- **Audit table `mcp_audit_log`**: `user_email, tool_name, input_params(jsonb), output_size, duration_ms, status, error_message, created_at`. Powers the Grafana dashboard directly from Postgres.
- **Grafana dashboard** (`mcp-server-observability.json`): Live Feed, Top Queries, User Activity, Slowest Calls. No retrieval-quality panels.
- **Feedback signals**: none. No thumbs, no agent-side relevance, no click-through.

## 7. Versioning / Freshness

- **Per-repo registry** (`registry/models.py`): `name, url, branch, status, chunk_count, file_count, last_indexed_at, index_error, dep_map`. **No commit SHA, no HEAD ref.**
- **Embedding model version**: not stored — neither per-chunk nor per-repo. Switching models requires full re-embed with no drift detection.
- **Schema / index version**: none. HNSW index params are hard-coded.
- **Graph version**: Neo4j nodes carry a `repo` property for isolation; `XREF` cross-repo edges are created only by manual `link_repos` call.
- **Cross-repo consistency**: repos are indexed at arbitrary times (current spread: 2026-04-07 → 2026-04-20). No synchronization; call-graph hits can reference deleted lines.
- **Refresh**: manual only (`index_repo` → Argo). No CronJob, no TTL, no webhook-driven reindex.

## 8. Research Readiness Assessment

**Current status: engineering prototype (trending toward internal platform).**

What's robust: production-shaped MCP surface (13 tools, OAuth, ServiceMonitor), working hybrid pgvector + Neo4j pipeline, real multi-repo coverage, Phoenix/Jaeger tracing, Argo-driven indexing, a live audit trail and dashboard.

What blocks "robust internal platform": the `repo="null-realm"` default silently returns zero hits for the system's own codebase; `service_deps` throws; graph has unfiltered built-ins as pseudo-symbols; test files routinely outrank production code; no BM25 fallback or reranker; non-code context (READMEs, SQL, Helm) is unindexed for most repos; staleness is silent (no commit SHA).

What blocks "publishable research prototype": no runnable eval harness, no metrics (recall@k / nDCG / MRR), a single annotated query, no ablations (vector-only vs + graph vs + rerank), no embedding-model or chunker comparison, no baseline (BM25, tree-sitter-only, full-file). The ingredients for a study are present — multi-repo corpus, hybrid retrieval, captured queries — but the measurement layer is unwritten. With an eval harness over `benchmark/queries/` computing recall@k and distractor-discrimination per archetype, plus at least one baseline, this crosses into publishable territory.
