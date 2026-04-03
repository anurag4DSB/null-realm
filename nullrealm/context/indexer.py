"""Multi-language code indexer with embedding support.

Parses source files (Python, JS/TS, Go) into CodeChunks, extracts
inter-symbol relationships, and optionally embeds + stores in pgvector.
"""

import argparse
import ast
import asyncio
import logging
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "site-packages",
    "dist",
    "build",
    ".next",
    "coverage",
    "vendor",
    ".yarn",
    "bower_components",
}


@dataclass
class CodeChunk:
    """A single indexed unit of source code."""

    text: str
    file_path: str
    symbol_name: str
    symbol_type: str  # "function", "class", "module"
    language: str = "python"
    line_start: int = 0
    line_end: int = 0
    imports: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class CodeRelationship:
    """A directed relationship between two code symbols."""

    source_file: str
    source_symbol: str
    relationship: str  # "IMPORTS", "CALLS", "INHERITS", "CONTAINS"
    target_file: str
    target_symbol: str


def _get_source_segment(source_lines: list[str], node: ast.AST) -> str:
    """Extract the source text for an AST node."""
    start = node.lineno - 1
    end = node.end_lineno if node.end_lineno else start + 1
    return "\n".join(source_lines[start:end])


def _extract_calls(node: ast.AST) -> list[str]:
    """Extract function/method call names from an AST node (best effort)."""
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(child.func.attr)
    return calls


def parse_python_file(file_path: str) -> tuple[list[CodeChunk], list[CodeRelationship]]:
    """Parse a Python file into code chunks and relationships using the ast module.

    Returns:
        Tuple of (chunks, relationships).
    """
    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        logger.warning("Skipping %s: %s", file_path, exc)
        return [], []

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        logger.warning("Syntax error in %s: %s", file_path, exc)
        return [], []

    source_lines = source.splitlines()
    chunks: list[CodeChunk] = []
    relationships: list[CodeRelationship] = []

    # Collect module-level imports
    module_imports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_imports.append(alias.name)
                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol="<module>",
                        relationship="IMPORTS",
                        target_file="",
                        target_symbol=alias.name,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            for alias in node.names:
                full_name = f"{module_name}.{alias.name}" if module_name else alias.name
                module_imports.append(full_name)
                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol="<module>",
                        relationship="IMPORTS",
                        target_file="",
                        target_symbol=full_name,
                    )
                )

    # Module-level docstring chunk
    module_doc = ast.get_docstring(tree) or ""
    if module_doc:
        chunks.append(
            CodeChunk(
                text=f'"""Module: {path.name}"""\n{module_doc}',
                file_path=file_path,
                symbol_name=path.stem,
                symbol_type="module",
                line_start=1,
                line_end=1,
                imports=module_imports,
                metadata={"docstring": module_doc},
            )
        )

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            chunk_text = _get_source_segment(source_lines, node)
            docstring = ast.get_docstring(node) or ""
            calls = _extract_calls(node)

            chunks.append(
                CodeChunk(
                    text=chunk_text,
                    file_path=file_path,
                    symbol_name=node.name,
                    symbol_type="function",
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    imports=module_imports,
                    metadata={
                        "docstring": docstring,
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                    },
                )
            )

            # CALLS relationships
            for call_name in calls:
                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol=node.name,
                        relationship="CALLS",
                        target_file="",
                        target_symbol=call_name,
                    )
                )

        elif isinstance(node, ast.ClassDef):
            chunk_text = _get_source_segment(source_lines, node)
            docstring = ast.get_docstring(node) or ""

            chunks.append(
                CodeChunk(
                    text=chunk_text,
                    file_path=file_path,
                    symbol_name=node.name,
                    symbol_type="class",
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    imports=module_imports,
                    metadata={"docstring": docstring},
                )
            )

            # INHERITS relationships
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name:
                    relationships.append(
                        CodeRelationship(
                            source_file=file_path,
                            source_symbol=node.name,
                            relationship="INHERITS",
                            target_file="",
                            target_symbol=base_name,
                        )
                    )

            # Extract methods as sub-chunks with CONTAINS relationship
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    method_text = _get_source_segment(source_lines, item)
                    method_text = textwrap.dedent(method_text)
                    method_doc = ast.get_docstring(item) or ""
                    method_calls = _extract_calls(item)

                    full_name = f"{node.name}.{item.name}"
                    chunks.append(
                        CodeChunk(
                            text=method_text,
                            file_path=file_path,
                            symbol_name=full_name,
                            symbol_type="function",
                            line_start=item.lineno,
                            line_end=item.end_lineno or item.lineno,
                            imports=module_imports,
                            metadata={
                                "docstring": method_doc,
                                "is_async": isinstance(item, ast.AsyncFunctionDef),
                                "class": node.name,
                            },
                        )
                    )

                    relationships.append(
                        CodeRelationship(
                            source_file=file_path,
                            source_symbol=node.name,
                            relationship="CONTAINS",
                            target_file=file_path,
                            target_symbol=full_name,
                        )
                    )

                    for call_name in method_calls:
                        relationships.append(
                            CodeRelationship(
                                source_file=file_path,
                                source_symbol=full_name,
                                relationship="CALLS",
                                target_file="",
                                target_symbol=call_name,
                            )
                        )

    return chunks, relationships


async def index_repo(
    repo_path: str,
    embed: bool = True,
    graph: bool = False,
    repo_name: str = "",
) -> tuple[list[CodeChunk], list[CodeRelationship], dict, "ServiceAnalysis | None"]:
    """Walk a repository and parse all supported source files.

    Args:
        repo_path: Root directory to index.
        embed: If True, embed chunks and store in pgvector.
        graph: If True, store relationships in Neo4j.
        repo_name: Repository name for Neo4j node tagging.

    Returns:
        Tuple of (all_chunks, all_relationships, dep_map, service_analysis).
        dep_map: dict of Scality package.json dependencies (empty if none).
        service_analysis: ServiceAnalysis object if graph=True, else None.
    """
    from collections import Counter

    from nullrealm.context.parsers import SUPPORTED_EXTENSIONS, parse_file

    repo = Path(repo_path).resolve()

    # Parse package.json for dependency map (used for cross-repo linking)
    from nullrealm.context.service_analyzer import parse_package_json
    dep_map = parse_package_json(repo)
    if dep_map:
        logger.info("Found %d Scality dependencies: %s", len(dep_map), list(dep_map.keys()))

    all_chunks: list[CodeChunk] = []
    all_relationships: list[CodeRelationship] = []

    source_files = [
        p for p in repo.rglob("*")
        if p.suffix in SUPPORTED_EXTENSIONS
        and not any(part in SKIP_DIRS for part in p.parts)
    ]

    # Log language breakdown
    ext_counts = Counter(p.suffix for p in source_files)
    logger.info(
        "Found %d source files in %s: %s",
        len(source_files),
        repo,
        ", ".join(f"{ext}={count}" for ext, count in ext_counts.most_common()),
    )

    for source_file in sorted(source_files):
        rel_path = str(source_file.relative_to(repo))
        chunks, rels = parse_file(str(source_file))

        # Normalize file paths to be relative
        for c in chunks:
            c.file_path = rel_path
        for r in rels:
            if r.source_file:
                try:
                    r.source_file = str(Path(r.source_file).relative_to(repo))
                except ValueError:
                    pass
            if r.target_file:
                try:
                    r.target_file = str(Path(r.target_file).relative_to(repo))
                except ValueError:
                    pass

        all_chunks.extend(chunks)
        all_relationships.extend(rels)

    logger.info("Parsed %d chunks and %d relationships", len(all_chunks), len(all_relationships))

    if embed and all_chunks:
        from nullrealm.context.embeddings import embed_texts
        from nullrealm.context.pgvector_store import PgVectorStore

        texts = [c.text for c in all_chunks]
        logger.info("Embedding %d chunks...", len(texts))
        embeddings = embed_texts(texts)
        logger.info("Got %d embeddings, storing in pgvector...", len(embeddings))

        store = PgVectorStore()
        await store.init()
        await store.store_embeddings(all_chunks, embeddings, repo_name=repo.name)
        logger.info("Stored %d embeddings in pgvector", len(embeddings))

    if graph and all_relationships:
        from nullrealm.context.neo4j_store import Neo4jStore

        logger.info("Storing %d relationships in Neo4j...", len(all_relationships))
        store = Neo4jStore()
        await store.store_graph(all_relationships, repo_name=repo_name or repo.name)
        await store.close()
        logger.info("Graph storage complete")

    # Run service analysis after all parsing is done
    if graph:
        from nullrealm.context.service_analyzer import analyze_service
        service_analysis = analyze_service(repo_name or repo.name, repo, all_chunks)
        logger.info(
            "Service analysis: %d connections, %d endpoints, %d topics",
            len(service_analysis.connections),
            len(service_analysis.endpoints),
            len(service_analysis.topics),
        )
    else:
        service_analysis = None

    return all_chunks, all_relationships, dep_map, service_analysis


def main():
    parser = argparse.ArgumentParser(description="Index a source code repo into pgvector")
    parser.add_argument("--repo", default=".", help="Path to repository root")
    parser.add_argument("--embed", action="store_true", help="Embed and store in pgvector")
    parser.add_argument("--graph", action="store_true", help="Store relationships (Task 2)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    chunks, rels, _dep_map, _svc = asyncio.run(index_repo(args.repo, embed=args.embed, graph=args.graph))
    print(f"\nIndexing complete: {len(chunks)} chunks, {len(rels)} relationships")

    # Print summary by symbol type and language
    from collections import Counter

    type_counts = Counter(c.symbol_type for c in chunks)
    for stype, count in type_counts.most_common():
        print(f"  {stype}: {count}")

    lang_counts = Counter(c.language for c in chunks)
    if len(lang_counts) > 1:
        print("\nBy language:")
        for lang, count in lang_counts.most_common():
            print(f"  {lang}: {count}")


if __name__ == "__main__":
    main()
