Index a Git repository into the null-realm knowledge graph (pgvector + Neo4j).

Usage: /index-repo <repo_url> [branch]

Example:
  /index-repo https://github.com/anurag4DSB/null-realm
  /index-repo git@github.com:scality/service-a.git develop

This will:
1. Clone the repo (or pull if already cached)
2. Parse all Python files via AST (functions, classes, modules)
3. Embed code chunks using Vertex AI text-embedding-005 via LiteLLM
4. Store embeddings in pgvector for semantic search
5. Store relationships in Neo4j knowledge graph
6. Generate REPO_INDEX.md summary via Claude

Prerequisites (local Kind):
- Port-forward PostgreSQL: kubectl port-forward svc/postgres -n null-realm 15432:5432 --context kind-null-realm &
- Port-forward Neo4j: kubectl port-forward svc/neo4j -n null-realm 7687:7687 --context kind-null-realm &
- Port-forward LiteLLM: kubectl port-forward svc/litellm -n null-realm 4000:4000 --context kind-null-realm &

Run the indexer:
```bash
DATABASE_URL=postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:15432/nullrealm \
NEO4J_URI=bolt://localhost:7687 \
LITELLM_URL=http://localhost:4000/v1 \
uv run python -c "
import asyncio
from nullrealm.context.repo_manager import index_repository
result = asyncio.run(index_repository('$ARGUMENTS'))
print(f'Indexed {result[\"repo_name\"]}: {result[\"chunks\"]} chunks, {result[\"relationships\"]} relationships')
"
```

Alternative: use the hopocalypse MCP tool (indexes on GKE, no port-forwards needed):
  Claude Code: "use index_repo to index https://github.com/org/repo"
