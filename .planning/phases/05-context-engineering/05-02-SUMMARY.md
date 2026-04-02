---
phase: 05-context-engineering
plan: 05-02
status: complete
completed: 2026-04-02
---

# Summary: 05-02 MCP Server + Graph RAG Tools + Context Assembly + Retrieval Transparency

## What Was Accomplished

1. **MCP server with Google OAuth at hopocalypse.nip.io** -- Streamable HTTP transport (MCP 2025-06-18 spec) at `hopocalypse.34.53.165.155.nip.io/mcp`. Google OAuth token flow with RFC 8414 discovery, dynamic client registration, and PKCE. Same Google credentials as OAuth2 Proxy, but token-based (not cookie-based) for MCP client compatibility.

2. **5 MCP tools registered**:
   - `code_search` -- pgvector semantic search over code embeddings. Input: query, repo (optional), k. Returns: file paths, symbol names, scores, code snippets.
   - `graph_query` -- Neo4j neighbor traversal. Input: symbol, depth. Returns: connected nodes with relationship types.
   - `graph_path` -- Neo4j shortest path between two symbols. Input: source, target. Returns: path nodes and edge types.
   - `service_map` -- Neo4j full service-to-service connection map. No params. Returns: all inter-file relationships.
   - `context_assemble` -- Hybrid retrieval combining vector search + graph walk. Input: task description, repos. Returns: assembled context with provenance.

3. **Context assembler with hybrid retrieval** -- `nullrealm/context/assembler.py` implements the full pipeline: REPO_INDEX.md inclusion, pgvector semantic search for starting points, Neo4j graph expansion (1-2 hops from vector hits), rank + deduplicate merged results. Returns `AssembledContext` with repo summary, vector results, graph paths, and total token count.

4. **`/context` command in Chainlit** -- Users type `/context <query>` to trigger hybrid retrieval and see exactly what the context assembler would provide to an agent. Displays retrieval steps as expandable `cl.Step` elements with scores and graph paths.

5. **LangGraph tool wrappers** -- `nullrealm/tools/builtins/code_search.py` and `nullrealm/tools/builtins/graph_query.py` wrap the same pgvector/Neo4j logic as LangChain `@tool` decorators for use by null-realm's own LangGraph agents. Added to research assistant's tool allowlist.

## Key Stats

- OAuth with RFC 8414 discovery + dynamic client registration + PKCE
- 5 MCP tools + 2 MCP resources (repo://null-realm/index, repo://null-realm/graph)
- MCP server runs at 3Gi memory on GKE (pgvector + Neo4j clients in-process)

## Files Created

```
nullrealm/mcp_server.py                           # MCP server (Streamable HTTP + stdio)
nullrealm/mcp_auth.py                             # Google OAuth token flow (RFC 8414 + PKCE)
nullrealm/mcp_tools.py                            # 5 MCP tool definitions
nullrealm/context/assembler.py                    # Hybrid context assembler (vector + graph)
nullrealm/tools/builtins/code_search.py           # LangGraph code_search tool wrapper
nullrealm/tools/builtins/graph_query.py           # LangGraph graph_query tool wrapper
Dockerfile.mcp                                    # MCP server container image
infra/k8s/gke/mcp/deployment.yaml                 # MCP server deployment on GKE
infra/k8s/gke/mcp/service.yaml                    # MCP server ClusterIP service
```

## Files Modified

```
ui/app.py                                         # Added /context command with retrieval transparency
nullrealm/api/websocket.py                        # Added retrieval event forwarding to Chainlit
```

## Deviations from Plan

1. **LiteLLM needed embedding model config** -- LiteLLM proxy did not have the Vertex AI embedding model (`text-embedding-005`) configured in its model list. Had to add it to the LiteLLM config before the MCP server could call `/v1/embeddings`.
2. **Repo filter mismatch ("app" vs "null-realm")** -- pgvector store was indexing with repo name "app" (from the Docker WORKDIR) but MCP tools were searching with repo filter "null-realm". Fixed by normalizing repo names during indexing.
3. **MCP server needs 3Gi memory** -- Initial deployment at 512Mi OOMKilled. The MCP server loads pgvector client + Neo4j driver + JWT auth in one process. Bumped to 3Gi on GKE Autopilot.
4. **Workload Identity for Vertex AI** -- MCP server pods needed the same Workload Identity SA binding as LiteLLM to call Vertex AI embeddings during context assembly. Routed through LiteLLM instead (consistent with ADR-010).
5. **`context_assemble` added as 5th MCP tool** -- Plan specified 4 tools (code_search, graph_query, graph_path, service_map). Added `context_assemble` as a 5th tool to expose the hybrid retrieval pipeline directly to MCP clients.

## Remaining (Parallel Agents)

- **Task 5: stdio MCP mode** -- Local stdio transport (`python -m nullrealm.mcp_server --stdio`) for Claude Code without network. Being built by a parallel agent.
- **Task 6: Grafana Code Knowledge Graph dashboard** -- Neo4j stats + search metrics in Grafana. Being built by a parallel agent.

## Verification Results

- [x] MCP server at hopocalypse.34.53.165.155.nip.io/mcp returns 401 without auth
- [x] Google OAuth flow works (authorize -> callback -> token with PKCE)
- [x] All 5 MCP tools return correct results
- [x] Both MCP resources accessible (repo://null-realm/index, repo://null-realm/graph)
- [x] Claude Code (remote) connects via OAuth and uses tools
- [x] Context assembler combines vector + graph results with provenance
- [x] Chainlit /context command shows retrieval transparency with scores
- [x] Langfuse traces show MCP tool usage
- [x] LangGraph tool wrappers registered and available to research assistant

## Next Step

**Phase 06**: Model Comparison + Eval -- multi-model LiteLLM config, Claude vs Gemini comparison workflow, LLM-as-judge, golden tests, Grafana dashboards.
