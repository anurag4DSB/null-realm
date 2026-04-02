"""Null Realm — Embedding Visualization (2D, 3D, Data Explorer, Graph Review, Summary Review)."""

import asyncio
import os
import subprocess
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from neo4j import GraphDatabase

st.set_page_config(page_title="Null Realm Embeddings", layout="wide", page_icon="\u2728")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:5432/nullrealm",
)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j.null-realm.svc.cluster.local:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j-null-realm")

REPO_INDEX_PATH = Path(os.getenv("REPO_INDEX_PATH", "repo-indexes/null-realm/REPO_INDEX.md"))


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from sync context (Streamlit is sync)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


@st.cache_data(ttl=300, show_spinner="Loading embeddings from pgvector...")
def load_data():
    """Load embeddings from DB, compute PaCMAP 2D + 3D reductions, return DataFrame."""
    from nullrealm.context.viz_export import load_embeddings_from_db, reduce_dimensions

    records = _run_async(load_embeddings_from_db(DATABASE_URL))
    if not records:
        return pd.DataFrame(), np.array([]), np.array([])

    embeddings = [r["embedding"] for r in records]

    # Build DataFrame (without the raw embedding column — too large for display)
    df = pd.DataFrame(
        {
            "repo": [r["repo"] for r in records],
            "file_path": [r["file_path"] for r in records],
            "module": [
                str(PurePosixPath(r["file_path"]).parent) for r in records
            ],
            "symbol_name": [r["symbol_name"] for r in records],
            "symbol_type": [r["symbol_type"] for r in records],
            "line_start": [r["line_start"] for r in records],
            "line_end": [r["line_end"] for r in records],
            "chunk_preview": [r["chunk_text"][:200] for r in records],
            "chunk_text": [r["chunk_text"] for r in records],
        }
    )

    # PaCMAP reductions
    coords_2d = reduce_dimensions(embeddings, n_components=2)
    coords_3d = reduce_dimensions(embeddings, n_components=3)

    df["x2d"] = coords_2d[:, 0]
    df["y2d"] = coords_2d[:, 1]
    df["x3d"] = coords_3d[:, 0]
    df["y3d"] = coords_3d[:, 1]
    df["z3d"] = coords_3d[:, 2]

    return df, coords_2d, coords_3d


# ---------------------------------------------------------------------------
# Neo4j helpers (sync driver — Streamlit is sync)
# ---------------------------------------------------------------------------

def _get_neo4j_driver():
    """Get or create a cached Neo4j sync driver."""
    if "neo4j_driver" not in st.session_state:
        st.session_state.neo4j_driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
    return st.session_state.neo4j_driver


@st.cache_data(ttl=120, show_spinner="Loading edges from Neo4j...")
def load_edges() -> pd.DataFrame:
    """Load all graph edges from Neo4j into a DataFrame."""
    driver = _get_neo4j_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:Symbol)-[r]->(b:Symbol)
            RETURN a.file AS source_file, a.name AS source_symbol,
                   r.type AS relationship,
                   b.file AS target_file, b.name AS target_symbol
            ORDER BY a.file, a.name
            """
        )
        records = [dict(record) for record in result]

    if not records:
        return pd.DataFrame(
            columns=["source_file", "source_symbol", "relationship",
                      "target_file", "target_symbol", "status"]
        )

    df = pd.DataFrame(records)
    df["status"] = "approved"
    return df


def apply_graph_changes(edges_df: pd.DataFrame, new_edges: list[dict]) -> tuple[int, int]:
    """Delete rejected edges and add new edges to Neo4j.

    Returns (deleted_count, added_count).
    """
    driver = _get_neo4j_driver()
    deleted = 0
    added = 0

    with driver.session() as session:
        # Delete rejected edges
        rejected = edges_df[edges_df["status"] == "rejected"]
        for _, row in rejected.iterrows():
            session.run(
                """
                MATCH (a:Symbol {file: $src_file, name: $src_symbol})
                      -[r:RELATES {type: $rel_type}]->
                      (b:Symbol {file: $tgt_file, name: $tgt_symbol})
                DELETE r
                """,
                src_file=row["source_file"],
                src_symbol=row["source_symbol"],
                rel_type=row["relationship"],
                tgt_file=row["target_file"],
                tgt_symbol=row["target_symbol"],
            )
            deleted += 1

        # Add new edges
        for edge in new_edges:
            session.run(
                """
                MERGE (a:Symbol {file: $src_file, name: $src_symbol})
                MERGE (b:Symbol {file: $tgt_file, name: $tgt_symbol})
                MERGE (a)-[r:RELATES {type: $rel_type}]->(b)
                """,
                src_file=edge["source_file"],
                src_symbol=edge["source_symbol"],
                rel_type=edge["relationship"],
                tgt_file=edge["target_file"],
                tgt_symbol=edge["target_symbol"],
            )
            added += 1

    return deleted, added


def get_unique_files() -> list[str]:
    """Get all unique file paths from Neo4j symbols."""
    driver = _get_neo4j_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (s:Symbol) WHERE s.file IS NOT NULL RETURN DISTINCT s.file AS file ORDER BY file"
        )
        return [record["file"] for record in result]


def get_unique_symbols(file_path: str) -> list[str]:
    """Get all symbol names for a given file."""
    driver = _get_neo4j_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (s:Symbol {file: $file}) RETURN DISTINCT s.name AS name ORDER BY name",
            file=file_path,
        )
        return [record["name"] for record in result]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

st.title("Null Realm \u2014 Embedding Explorer")

try:
    df, coords_2d, coords_3d = load_data()
except Exception as exc:
    st.error(f"Failed to load embeddings: {exc}")
    st.info(
        "Make sure PostgreSQL is reachable and the `code_embeddings` table exists. "
        "Set `DATABASE_URL` env var if needed."
    )
    st.stop()

if df.empty:
    st.warning("No embeddings found in the database. Run the indexer first.")
    st.stop()

st.caption(f"{len(df)} code chunks loaded | PaCMAP-reduced to 2D and 3D")

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
st.sidebar.header("Filters")

repos = sorted(df["repo"].unique())
selected_repos = st.sidebar.multiselect("Repository", repos, default=repos)

modules = sorted(df["module"].unique())
selected_modules = st.sidebar.multiselect("Module (directory)", modules, default=modules)

symbol_types = sorted(df["symbol_type"].unique())
selected_types = st.sidebar.multiselect("Symbol type", symbol_types, default=symbol_types)

mask = (
    df["repo"].isin(selected_repos)
    & df["module"].isin(selected_modules)
    & df["symbol_type"].isin(selected_types)
)
filtered = df[mask]

st.sidebar.metric("Showing", f"{len(filtered)} / {len(df)} chunks")

# Color-by selector
color_by = st.sidebar.radio("Color by", ["module", "symbol_type", "repo"], index=0)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_2d, tab_3d, tab_data, tab_graph, tab_summary = st.tabs(
    ["2D Scatter", "3D Scatter", "Data Table", "Graph Review", "Summary Review"]
)

# ---- Tab 1: 2D scatter ----
with tab_2d:
    fig2d = px.scatter(
        filtered,
        x="x2d",
        y="y2d",
        color=color_by,
        hover_data={
            "file_path": True,
            "symbol_name": True,
            "symbol_type": True,
            "chunk_preview": True,
            "x2d": False,
            "y2d": False,
        },
        title="PaCMAP 2D Projection",
        height=700,
    )
    fig2d.update_traces(marker=dict(size=6, opacity=0.8))
    fig2d.update_layout(
        xaxis_title="PaCMAP-1",
        yaxis_title="PaCMAP-2",
        legend=dict(orientation="h", yanchor="bottom", y=-0.3),
    )
    st.plotly_chart(fig2d, use_container_width=True)

# ---- Tab 2: 3D scatter ----
with tab_3d:
    fig3d = px.scatter_3d(
        filtered,
        x="x3d",
        y="y3d",
        z="z3d",
        color=color_by,
        hover_data={
            "file_path": True,
            "symbol_name": True,
            "symbol_type": True,
            "chunk_preview": True,
            "x3d": False,
            "y3d": False,
            "z3d": False,
        },
        title="PaCMAP 3D Projection",
        height=750,
    )
    fig3d.update_traces(marker=dict(size=3, opacity=0.8))
    fig3d.update_layout(
        scene=dict(
            xaxis_title="PaCMAP-1",
            yaxis_title="PaCMAP-2",
            zaxis_title="PaCMAP-3",
        ),
    )
    st.plotly_chart(fig3d, use_container_width=True)

# ---- Tab 3: Data table ----
with tab_data:
    st.subheader("All Code Chunks")

    search_text = st.text_input("Search in code text", "")
    if search_text:
        text_mask = filtered["chunk_text"].str.contains(search_text, case=False, na=False)
        table_df = filtered[text_mask]
    else:
        table_df = filtered

    st.dataframe(
        table_df[
            [
                "repo",
                "file_path",
                "symbol_name",
                "symbol_type",
                "line_start",
                "line_end",
                "chunk_preview",
            ]
        ],
        use_container_width=True,
        height=600,
    )

    # Expandable code viewer
    if not table_df.empty:
        st.subheader("Code Viewer")
        idx = st.selectbox(
            "Select chunk",
            table_df.index,
            format_func=lambda i: f"{table_df.loc[i, 'file_path']}:{table_df.loc[i, 'symbol_name']}",
        )
        if idx is not None:
            st.code(table_df.loc[idx, "chunk_text"], language="python")

# ---- Tab 4: Graph Review ----
with tab_graph:
    st.header("Graph Review")
    st.markdown("Review and correct Neo4j graph edges")

    try:
        edges_df = load_edges()
    except Exception as exc:
        st.error(f"Failed to load edges from Neo4j: {exc}")
        st.info(
            f"Make sure Neo4j is reachable at `{NEO4J_URI}`. "
            "Set `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` env vars if needed."
        )
        edges_df = pd.DataFrame(
            columns=["source_file", "source_symbol", "relationship",
                      "target_file", "target_symbol", "status"]
        )

    if not edges_df.empty:
        # Summary counts
        n_total = len(edges_df)
        col_counts = st.container()

        # Editable data table
        edited_df = st.data_editor(
            edges_df,
            column_config={
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=["approved", "rejected"],
                    default="approved",
                    width="small",
                ),
            },
            use_container_width=True,
            height=500,
            num_rows="fixed",
            key="graph_editor",
        )

        n_rejected = len(edited_df[edited_df["status"] == "rejected"])

        # Initialize new edges in session state
        if "new_edges" not in st.session_state:
            st.session_state.new_edges = []

        n_new = len(st.session_state.new_edges)
        col_counts.caption(
            f"{n_total} edges ({n_rejected} rejected, {n_new} new)"
        )

        # Add new edge form
        st.subheader("Add New Edge")
        with st.form("add_edge_form", clear_on_submit=True):
            try:
                files = get_unique_files()
            except Exception:
                files = []

            if files:
                acol1, acol2 = st.columns(2)
                with acol1:
                    src_file = st.selectbox("Source file", files, key="src_file_sel")
                    src_symbols = get_unique_symbols(src_file) if src_file else []
                    src_symbol = st.selectbox("Source symbol", src_symbols, key="src_sym_sel")
                with acol2:
                    tgt_file = st.selectbox("Target file", files, key="tgt_file_sel")
                    tgt_symbols = get_unique_symbols(tgt_file) if tgt_file else []
                    tgt_symbol = st.selectbox("Target symbol", tgt_symbols, key="tgt_sym_sel")

                rel_type = st.selectbox(
                    "Relationship type",
                    ["IMPORTS", "CALLS", "INHERITS", "DEPENDS_ON"],
                )

                submitted = st.form_submit_button("Add Edge")
                if submitted and src_file and src_symbol and tgt_file and tgt_symbol:
                    st.session_state.new_edges.append({
                        "source_file": src_file,
                        "source_symbol": src_symbol,
                        "relationship": rel_type,
                        "target_file": tgt_file,
                        "target_symbol": tgt_symbol,
                    })
                    st.success(
                        f"Added: {src_symbol} --[{rel_type}]--> {tgt_symbol}"
                    )
                    st.rerun()
            else:
                st.warning("No files found in Neo4j graph.")
                st.form_submit_button("Add Edge", disabled=True)

        # Show pending new edges
        if st.session_state.new_edges:
            st.subheader("Pending New Edges")
            new_df = pd.DataFrame(st.session_state.new_edges)
            st.dataframe(new_df, use_container_width=True)
            if st.button("Clear pending edges"):
                st.session_state.new_edges = []
                st.rerun()

        # Apply changes button
        st.divider()
        if st.button("Apply Changes", type="primary"):
            with st.spinner("Applying changes to Neo4j..."):
                deleted, added = apply_graph_changes(
                    edited_df, st.session_state.new_edges
                )
            st.success(f"Done! Deleted {deleted} edges, added {added} edges.")
            st.session_state.new_edges = []
            # Clear the edge cache so next load reflects changes
            load_edges.clear()
            st.rerun()
    else:
        st.info("No edges found in the graph. Index a repository first.")

# ---- Tab 5: Summary Review ----
with tab_summary:
    st.header("Summary Review")
    st.markdown("Review and edit REPO_INDEX.md")

    # Load the REPO_INDEX.md file
    repo_index_content = ""
    if REPO_INDEX_PATH.exists():
        repo_index_content = REPO_INDEX_PATH.read_text(encoding="utf-8")
    else:
        st.warning(f"File not found: `{REPO_INDEX_PATH}`. Save below to create it.")

    # Editable text area
    edited_content = st.text_area(
        "Edit REPO_INDEX.md",
        value=repo_index_content,
        height=600,
        key="summary_editor",
    )

    bcol1, bcol2 = st.columns(2)

    with bcol1:
        if st.button("Save", type="primary"):
            try:
                REPO_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
                REPO_INDEX_PATH.write_text(edited_content, encoding="utf-8")
                st.success(f"Saved to `{REPO_INDEX_PATH}`")
            except Exception as exc:
                st.error(f"Failed to save: {exc}")

    with bcol2:
        if st.button("Regenerate"):
            with st.spinner("Regenerating summary via LLM (this may take a minute)..."):
                try:
                    result = subprocess.run(
                        [
                            "uv", "run", "python", "-m", "nullrealm.context.summaries",
                            "--repo", ".",
                            "--output", "repo-indexes/",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    if result.returncode == 0:
                        st.success("Regeneration complete! Reloading...")
                        st.rerun()
                    else:
                        st.error(f"Regeneration failed:\n```\n{result.stderr}\n```")
                except subprocess.TimeoutExpired:
                    st.error("Regeneration timed out after 3 minutes.")
                except Exception as exc:
                    st.error(f"Failed to run regeneration: {exc}")

    # Preview rendered markdown
    st.divider()
    st.subheader("Preview")
    st.markdown(edited_content)
