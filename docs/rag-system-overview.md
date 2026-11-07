# Null-Realm RAG System — Structured Overview

## 1. System Goal

A shared, code-aware "brain" for R&D agents: index many Scality microservice repos and expose semantic + structural retrieval over them via an MCP server. Built to answer cross-repo questions — *"where is symbol X called?"*, *"what does service Y depend on?"*, *"find code that does Z"*, *"shortest call-path from A to B"* — and to assemble a grounded context bundle before an LLM agent reasons or writes code.

## 2. Data Ingestion

- **Sources**: arbitrary Git repos (local, HTTPS, SSH+GitHub PAT), triggered by the `index_repo` MCP tool, which fires an Argo Workflow in-cluster. Clones into `/tmp/null-realm-repos/` (`repo_manager.py:167`).
- **Extraction**: language-specific ASTs. Python → stdlib `ast` (`indexer.py:82`). JS/TS/JSX/TSX → tree-sitter (`ecmascript_common.py`). Go → tree-sitter with receiver-type handling (`go_parser.py`).
- **Preprocessing**: directory skiplist (`.git`, `node_modules`, `venv`, `dist`, …) at `indexer.py:17`; extension-only filter (no binary sniff, no `.gitignore`); repo-relative paths.
- **Service pass**: `service_analyzer.py` detects inter-service edges via a client-lib map (e.g. `vaultclient` → vault), plus Kafka topics, HTTP endpoints, `package.json` deps.

## 3. Chunking Strategy

- **Granularity**: symbol-level only — one chunk per function, class, method, module docstring, interface, or enum. No sliding windows, no overlap.
- **Metadata** per `CodeChunk` (`indexer.py:37`): `text`, `file_path`, `symbol_name`, `symbol_type`, `language`, `line_start/end`, `imports`, plus `{docstring, is_async, class, receiver_type, kind}`.

## 4. Embedding Setup

- **Model**: Vertex AI `text-embedding-005` via in-cluster LiteLLM proxy (`litellm.null-realm.svc:4000`). Fallback: `sentence-transformers/all-mpnet-base-v2`.
- **Dimension**: 768 (`EMBEDDING_DIM`, `pgvector_store.py:28`).
- **Batching**: 5 texts/request (avoids Vertex's 20K-token/request cap).
- **Input**: raw chunk source only — docstrings/summaries are stored as metadata, not separately embedded.

## 5. Storage Layer

- **pgvector** on GCP CloudSQL (async SQLAlchemy + asyncpg).
- **Table `code_embeddings`**: `id`, `chunk_text` (≤10 KB), `embedding vector(768)`, `repo`, `file_path`, `symbol_name`, `symbol_type`, `line_start/end`, `metadata_ jsonb`, `created_at`.
- **Index**: HNSW (`m=16, ef_construction=64`, `vector_cosine_ops`).
- **Re-index**: delete-then-insert per repo; inserts batched in 100s. Audit writes to `mcp_audit_log` (fire-and-forget).

## 6. Retrieval Pipeline

`code_search(query, repo, k)` → embed query → pgvector `cosine_distance` ASC LIMIT k. Similarity = `1 - distance`. Default **k=10**. Only filter is `repo`. **No reranking** (no cross-encoder, MMR, or LLM rerank).

## 7. Hybrid / Graph Retrieval

- **No BM25/FTS/trigram/ripgrep** — vector-only.
- **Neo4j knowledge graph** (async driver, Cypher).
  - **Nodes**: `Symbol{name,file,repo,type}` plus service-level `Service`, `Endpoint`, `Topic`, `InfraService`.
  - **Edges**: `RELATES{type ∈ IMPORTS|CALLS|INHERITS|CONTAINS}`; service edges `DEPENDS_ON`, `HTTP_CALLS`, `USES_CLIENT`, `USES_INFRA`, `CONFIGURED_BY`, `BUILT_FROM`; cross-repo `XREF`.
  - **Queries**: `query_neighbors(symbol, depth)`, `query_path(src,tgt)`, `query_service_map`, `query_service_deps`.

## 8. Context Construction

`context_assemble` (`assembler.py`) concatenates three blocks into a markdown prompt:
1. Static `REPO_INDEX.md` (first 2000 chars).
2. Top-5 pgvector hits, each truncated to 500 chars.
3. Top-3 of those expanded 1 hop in Neo4j → up to 10 neighbor symbols.

No dedup, no rank fusion; token budget estimated as `chars/4`.

## 9. LLM / Agent Layer

The MCP server itself calls **no LLM** — pure retrieval. A separate LangGraph ReAct worker (`worker/langgraph_agent.py`) talks to Claude Sonnet via LiteLLM, streams over NATS, carries only a `file_read` tool; Chainlit fronts it. Primary consumers are external agents (Claude Code, IDEs) hitting the 13 MCP tools: `code_search`, `get_full_chunk`, `graph_query`, `graph_path`, `service_map`, `context_assemble`, `index_repo`, `add_repo`, `list_repos`, `delete_repo_index`, `link_repos`, `service_topology`, `service_deps`. GKE stack: MCP (:8090, own OAuth), Neo4j StatefulSet (auth off), LiteLLM, Phoenix, Jaeger, Grafana, Argo, Chainlit, API server; Traefik + oauth2-proxy; `ServiceMonitor` scrapes `mcp_tool_calls_total` / `mcp_tool_duration_seconds`; OTEL spans to Jaeger + Phoenix.

## 10. Known Limitations

- Vector-only — exact-identifier queries rely on embedding recall; no BM25/path/language filters.
- No reranking/MMR → near-duplicate symbols crowd top-k.
- Symbol-only chunking skips READMEs, SQL, YAML, Dockerfiles; file-level narrative lost.
- Languages limited to Py/JS/TS/Go (no Java/Rust/C/C++/shell).
- `chunk_text` capped at 10 KB; assembled context hard-truncated at 500 chars/hit with no token accounting.
- Neo4j auth disabled in-cluster; graph expansion fixed at depth=1 in the assembler.
- No `.gitignore` handling — vendored/generated code can pollute the index.
- Re-index is delete-then-insert, not incremental — large repos re-embed every run.
