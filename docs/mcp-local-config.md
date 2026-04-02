# Local MCP Server for Claude Code

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "null-realm-local": {
      "command": "uv",
      "args": ["run", "python", "-m", "nullrealm.mcp_server", "--stdio"],
      "cwd": "/Users/anurag4dsb/anurag-builds-things/agents/building-null-realm/null-realm",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:15432/nullrealm",
        "NEO4J_URI": "bolt://localhost:7687"
      }
    }
  }
}
```

## Prerequisites

Port-forward PostgreSQL and Neo4j from the Kind cluster before using:

```bash
kubectl port-forward svc/postgres -n null-realm 15432:5432 --context kind-null-realm &
kubectl port-forward svc/neo4j -n null-realm 7687:7687 --context kind-null-realm &
```

## Available Tools

| Tool | Description |
|------|-------------|
| `code_search` | Semantic code search across repositories (pgvector) |
| `graph_query` | Find connected code symbols in the Neo4j knowledge graph |
| `graph_path` | Find shortest path between two code symbols |
| `service_map` | Show all file-to-file connections in the codebase |
| `context_assemble` | Hybrid Graph RAG: combines REPO_INDEX.md + vector search + graph expansion |

## Available Resources

| Resource | Description |
|----------|-------------|
| `repo://null-realm/index` | REPO_INDEX.md architecture summary |

## Verified

Tested 2026-04-02. Server responds with protocol version `2025-11-25`, server name `null-realm` v1.26.0, all 5 tools and 1 resource available.
