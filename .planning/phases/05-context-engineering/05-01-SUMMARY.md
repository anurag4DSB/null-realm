---
phase: 05-context-engineering
plan: 05-01
status: complete
completed: 2026-04-02
---

# Summary: 05-01 Repo Indexing Pipeline (AST Parsing + Embeddings + Knowledge Graph + Visualizations)

## What Was Accomplished

1. **AST indexer with language-aware code chunking** -- Python AST parsing splits code into semantic chunks (functions, classes, modules). Extracts relationships: imports, function calls, class inheritance. CLI: `python -m nullrealm.context.indexer --repo . --embed --graph`.

2. **Vertex AI embeddings via LiteLLM proxy** -- 768-dimension embeddings from Vertex AI `text-embedding-005` routed through LiteLLM `/v1/embeddings` endpoint. No direct Vertex AI SDK calls from app pods -- LiteLLM already runs with the correct Workload Identity SA binding.

3. **pgvector store with HNSW index** -- `code_embeddings` table with vector(768), repo, file_path, symbol_name, symbol_type, metadata JSONB. HNSW index for fast ANN search. Cosine similarity search via `PgVectorStore.search()`.

4. **Neo4j knowledge graph** -- Neo4j 5 community edition on GKE. Node types: File, Function, Class, Module. Edge types: IMPORTS, CALLS, INHERITS, CONTAINS. Populated from AST relationship extraction during indexing.

5. **REPO_INDEX.md generation** -- LLM-generated structured repo summary via `nullrealm/context/summaries.py`. Includes architecture overview, service map, key abstractions, API surface, annotated file tree. Output at `repo-indexes/null-realm/REPO_INDEX.md`.

6. **5 visualization tools deployed on GKE**:
   - **Streamlit embedding explorer** (`embeddings.34.53.165.155.nip.io`) -- 2D PaCMAP scatter plot with hover code snippets, cluster coloring by module/repo
   - **Apple Embedding Atlas** (`atlas.34.53.165.155.nip.io`) -- WebGPU 2D map with auto-clustering, density contours, nearest neighbor search
   - **TensorBoard Projector** (`tensorboard.34.53.165.155.nip.io`) -- 3D rotation of embedding space with PCA/t-SNE/UMAP toggle
   - **Renumics Spotlight** (`spotlight.34.53.165.155.nip.io`) -- Dataset explorer for filtering by repo, language, chunk type; outlier detection
   - **Neo4j Browser** (`neo4j.34.53.165.155.nip.io`) -- Interactive graph exploration via Cypher queries

7. **Human review interface** -- Streamlit tab for reviewing and correcting the index: approve/reject graph edges, mark chunks as noise, edit REPO_INDEX.md inline, re-index button for incremental updates.

## Key Stats

- **179 chunks** indexed from null-realm repo
- **1246 relationships** in Neo4j knowledge graph
- **768-dimension** Vertex AI embeddings (text-embedding-005)
- PaCMAP reduction to 2D and 3D coordinates for visualization

## Files Created

```
nullrealm/context/__init__.py                     # Context engineering package
nullrealm/context/indexer.py                       # AST parser + code chunker + CLI
nullrealm/context/embeddings.py                    # Vertex AI embeddings via LiteLLM
nullrealm/context/pgvector_store.py                # pgvector store with HNSW index
nullrealm/context/neo4j_store.py                   # Neo4j knowledge graph store
nullrealm/context/summaries.py                     # REPO_INDEX.md generation via LLM
nullrealm/context/viz_export.py                    # PaCMAP reduction + export formats
viz/app.py                                         # Streamlit embedding explorer + review UI
viz/tools/atlas_entrypoint.sh                      # Apple Atlas container entrypoint
viz/tools/export_data.py                           # Data export for visualization tools
viz/tools/projector_entrypoint.sh                  # TensorBoard Projector entrypoint
viz/tools/spotlight_entrypoint.sh                  # Spotlight container entrypoint
viz/tools/spotlight_server.py                      # Spotlight Python server
Dockerfile.viz                                     # Streamlit embedding explorer image
Dockerfile.atlas                                   # Apple Embedding Atlas image
Dockerfile.projector                               # TensorBoard Projector image
Dockerfile.spotlight                               # Renumics Spotlight image
infra/k8s/gke/neo4j/statefulset.yaml              # Neo4j StatefulSet on GKE
infra/k8s/gke/neo4j/service.yaml                  # Neo4j Service (7474 + 7687)
infra/k8s/gke/embedding-viz/deployment.yaml        # Viz tools deployment (Streamlit, Atlas, Projector, Spotlight)
infra/k8s/gke/embedding-viz/service.yaml           # Viz tools services
repo-indexes/null-realm/REPO_INDEX.md              # Generated repo summary
```

## Deviations from Plan

1. **Vertex AI needed Workload Identity** -- Direct `google-cloud-aiplatform` SDK calls failed from app pods because only the LiteLLM ServiceAccount has the Workload Identity binding for Vertex AI. Routed all embeddings through LiteLLM `/v1/embeddings` instead of calling Vertex AI directly. This became ADR-010.
2. **sentence-transformers fallback = 500MB download** -- The planned local fallback (`all-MiniLM-L6-v2`) downloads 500MB of model weights on first run. Not viable for container images. Local dev also routes through LiteLLM (which can use the Vertex AI fallback or a local model).
3. **Neo4j auth=none** -- Plan called for `neo4j/neo4j-null-realm` credentials. Simplified to `NEO4J_AUTH=none` since Neo4j is cluster-internal only. No external access to bolt port except via explicit port-forward or LoadBalancer.
4. **Neo4j Bolt exposed via LoadBalancer** -- Neo4j Browser works at the HTTP subdomain, but Bolt protocol (7687) needed for the Python driver from MCP server. Exposed Bolt via a separate LoadBalancer service at `35.233.44.47:7687`.
5. **5 visualization tools instead of 4** -- Plan listed 4 viz tools (Atlas, TensorBoard, Spotlight, Neo4j Browser). Added Streamlit as the primary explorer with the review interface, making 5 total.

## Verification Results

- [x] AST parser handles Python files, extracts functions/classes/imports
- [x] Vertex AI embeddings stored in pgvector with HNSW index (179 chunks)
- [x] Neo4j knowledge graph populated with 1246 relationships
- [x] PaCMAP reduction produces meaningful 2D/3D coordinates
- [x] Streamlit explorer at embeddings.34.53.165.155.nip.io shows scatter plot
- [x] Apple Atlas at atlas.34.53.165.155.nip.io shows 2D embedding map
- [x] TensorBoard at tensorboard.34.53.165.155.nip.io shows 3D projector
- [x] Spotlight at spotlight.34.53.165.155.nip.io shows dataset explorer
- [x] Neo4j Browser at neo4j.34.53.165.155.nip.io shows interactive graph
- [x] pgvector semantic search returns relevant results
- [x] REPO_INDEX.md generated and accurate
- [x] Human review interface allows edge approval/rejection and chunk management

## Next Step

**05-02**: MCP server with Google OAuth + code_search/graph_query tools + context assembly + retrieval transparency in Chainlit.
