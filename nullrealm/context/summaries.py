"""Generate REPO_INDEX.md summaries using LLM via LiteLLM proxy.

Collects repo data (file tree, AST signatures, key file contents, graph stats)
and sends it to an LLM to produce a structured repository index document.
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path

import httpx

from nullrealm.context.indexer import SKIP_DIRS, parse_python_file

logger = logging.getLogger(__name__)


def collect_file_tree(repo_path: Path) -> str:
    """Walk the repo and return an annotated file tree string.

    Skips .git, venv, __pycache__, node_modules, and similar directories.
    """
    lines: list[str] = []
    repo_path = repo_path.resolve()

    for dirpath, dirnames, filenames in os.walk(repo_path):
        # Filter out skip dirs in-place so os.walk doesn't descend
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in SKIP_DIRS and not d.startswith(".")
        ]

        rel_dir = os.path.relpath(dirpath, repo_path)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1

        if depth > 3:
            continue  # Don't go too deep

        indent = "  " * depth
        dir_name = os.path.basename(dirpath) if depth > 0 else repo_path.name
        lines.append(f"{indent}{dir_name}/")

        for f in sorted(filenames):
            if f.startswith(".") and f not in (".env.example",):
                continue
            lines.append(f"{indent}  {f}")

    return "\n".join(lines)


def collect_ast_signatures(repo_path: Path) -> str:
    """Parse Python files and return function/class signatures."""
    repo_path = repo_path.resolve()
    signatures: list[str] = []

    py_files = sorted(
        p for p in repo_path.rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.parts)
        and "site-packages" not in str(p)
    )

    for py_file in py_files:
        rel_path = py_file.relative_to(repo_path)
        chunks, _rels = parse_python_file(str(py_file))
        if not chunks:
            continue

        file_sigs: list[str] = []
        for chunk in chunks:
            if chunk.symbol_type == "function":
                prefix = "async " if chunk.metadata.get("is_async") else ""
                class_name = chunk.metadata.get("class")
                if class_name:
                    file_sigs.append(f"  {prefix}def {chunk.symbol_name}()")
                else:
                    file_sigs.append(f"  {prefix}def {chunk.symbol_name}()")
            elif chunk.symbol_type == "class":
                file_sigs.append(f"  class {chunk.symbol_name}")
            elif chunk.symbol_type == "module":
                doc = chunk.metadata.get("docstring", "")
                if doc:
                    first_line = doc.split("\n")[0][:80]
                    file_sigs.append(f"  # {first_line}")

        if file_sigs:
            signatures.append(f"\n{rel_path}:")
            signatures.extend(file_sigs)

    return "\n".join(signatures)


def collect_key_files(repo_path: Path) -> str:
    """Read contents of key files (main.py, config.py, top-level __init__.py)."""
    repo_path = repo_path.resolve()
    key_patterns = [
        "nullrealm/main.py",
        "nullrealm/config.py",
        "nullrealm/__init__.py",
        "tasks.py",
    ]

    contents: list[str] = []
    for pattern in key_patterns:
        fp = repo_path / pattern
        if fp.exists():
            try:
                text = fp.read_text(encoding="utf-8")
                # Truncate to first 80 lines to keep prompt compact
                lines = text.splitlines()[:80]
                truncated = "\n".join(lines)
                if len(text.splitlines()) > 80:
                    truncated += f"\n... ({len(text.splitlines()) - 80} more lines)"
                contents.append(f"\n--- {pattern} ---\n{truncated}")
            except (OSError, UnicodeDecodeError):
                pass

    return "\n".join(contents)


async def collect_graph_stats() -> str:
    """Query Neo4j for graph statistics. Returns empty string on failure."""
    try:
        from nullrealm.context.neo4j_store import Neo4jStore

        store = Neo4jStore()
        stats_lines: list[str] = []

        async with store._driver.session() as session:
            # Total nodes and edges
            node_result = await session.run("MATCH (n:Symbol) RETURN count(n) AS cnt")
            node_record = await node_result.single()
            node_count = node_record["cnt"] if node_record else 0

            edge_result = await session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            edge_record = await edge_result.single()
            edge_count = edge_record["cnt"] if edge_record else 0

            stats_lines.append(f"Total nodes: {node_count}")
            stats_lines.append(f"Total edges: {edge_count}")

            # Top connected files (by edge count)
            top_result = await session.run(
                """
                MATCH (a:Symbol)-[r]->(b:Symbol)
                WHERE a.file IS NOT NULL AND a.file <> ''
                RETURN a.file AS file, count(r) AS edge_count
                ORDER BY edge_count DESC
                LIMIT 10
                """
            )
            top_files = [dict(record) async for record in top_result]
            if top_files:
                stats_lines.append("\nTop connected files:")
                for rec in top_files:
                    stats_lines.append(f"  {rec['file']}: {rec['edge_count']} edges")

            # Relationship type distribution
            rel_result = await session.run(
                """
                MATCH ()-[r]->()
                RETURN r.type AS rel_type, count(r) AS cnt
                ORDER BY cnt DESC
                """
            )
            rel_types = [dict(record) async for record in rel_result]
            if rel_types:
                stats_lines.append("\nRelationship types:")
                for rec in rel_types:
                    stats_lines.append(f"  {rec['rel_type']}: {rec['cnt']}")

        await store.close()
        return "\n".join(stats_lines)

    except Exception as exc:
        logger.warning("Could not collect graph stats from Neo4j: %s", exc)
        return "(Neo4j unavailable — graph stats skipped)"


async def generate_summary(repo_name: str, repo_data: str) -> str:
    """Send repo data to LLM via LiteLLM and get back a REPO_INDEX.md."""
    litellm_url = os.getenv(
        "LITELLM_URL", "http://litellm.null-realm.svc.cluster.local:4000/v1"
    )

    prompt = f"""Generate a REPO_INDEX.md for the repository "{repo_name}".

Include these sections:
# {repo_name}

## Architecture Overview
(2-3 paragraphs explaining what this project does and how it's structured)

## Service Map
(which components talk to which, based on the graph data)

## Key Abstractions
(main classes, patterns, important interfaces)

## API Surface
(HTTP endpoints, WebSocket routes, CLI commands)

## File Tree (annotated)
(directory structure with one-line description per important file)

## Key Files
(3-5 most important files with brief summaries)

Here is the repository data:
{repo_data}
"""

    logger.info(
        "Sending prompt to LiteLLM (%d chars, ~%d tokens)",
        len(prompt),
        len(prompt) // 4,
    )

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{litellm_url}/chat/completions",
            json={
                "model": "claude-sonnet",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000,
            },
            headers={"Authorization": "Bearer not-needed"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def run(repo_path: str, output_dir: str) -> str:
    """Main entry point: collect data, generate summary, save to file."""
    repo = Path(repo_path).resolve()
    repo_name = repo.name

    print(f"Collecting data for repo: {repo_name} ({repo})")

    # Collect all repo data
    print("  Collecting file tree...")
    file_tree = collect_file_tree(repo)

    print("  Collecting AST signatures...")
    ast_sigs = collect_ast_signatures(repo)

    print("  Collecting key file contents...")
    key_files = collect_key_files(repo)

    print("  Collecting graph stats from Neo4j...")
    graph_stats = await collect_graph_stats()

    # Assemble repo data payload
    repo_data = f"""=== FILE TREE ===
{file_tree}

=== AST SIGNATURES (functions, classes) ===
{ast_sigs}

=== KEY FILE CONTENTS ===
{key_files}

=== GRAPH STATS (Neo4j) ===
{graph_stats}
"""

    print(f"  Total repo data: {len(repo_data)} chars (~{len(repo_data) // 4} tokens)")

    # Send to LLM
    print("  Generating summary via LLM...")
    summary = await generate_summary(repo_name, repo_data)

    # Save output
    out_path = Path(output_dir) / repo_name
    out_path.mkdir(parents=True, exist_ok=True)
    index_file = out_path / "REPO_INDEX.md"
    index_file.write_text(summary, encoding="utf-8")

    print(f"\n  Saved to: {index_file}")
    print(f"  Summary length: {len(summary)} chars")
    print(f"\n{'=' * 60}")
    print(summary)
    print(f"{'=' * 60}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Generate REPO_INDEX.md summaries using LLM"
    )
    parser.add_argument(
        "--repo", default=".", help="Path to repository root (default: .)"
    )
    parser.add_argument(
        "--output",
        default="repo-indexes/",
        help="Output directory for indexes (default: repo-indexes/)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run(args.repo, args.output))


if __name__ == "__main__":
    main()
