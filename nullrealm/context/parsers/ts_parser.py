"""TypeScript/TSX code parser using tree-sitter.

Extends the shared ECMAScript parser with TypeScript-specific constructs:
interface declarations, enum declarations, and TSX support.
"""

from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_typescript as ts_typescript
from tree_sitter import Language, Parser

from nullrealm.context.indexer import CodeChunk, CodeRelationship
from nullrealm.context.parsers.ecmascript_common import (
    _find_child_by_type,
    _node_text,
    parse_ecmascript_tree,
)

logger = logging.getLogger(__name__)

TS_LANGUAGE = Language(ts_typescript.language_typescript())
TSX_LANGUAGE = Language(ts_typescript.language_tsx())

_ts_parser = Parser(TS_LANGUAGE)
_tsx_parser = Parser(TSX_LANGUAGE)


def parse_file(file_path: str) -> tuple[list[CodeChunk], list[CodeRelationship]]:
    """Parse a TypeScript/TSX file into code chunks and relationships."""
    path = Path(file_path)
    try:
        source = path.read_bytes()
    except OSError as exc:
        logger.warning("Skipping %s: %s", file_path, exc)
        return [], []

    # Select parser based on extension
    parser = _tsx_parser if path.suffix == ".tsx" else _ts_parser

    try:
        tree = parser.parse(source)
    except Exception as exc:
        logger.warning("Parse error in %s: %s", file_path, exc)
        return [], []

    # Get base ECMAScript chunks/relationships
    chunks, relationships = parse_ecmascript_tree(
        file_path, source, tree.root_node, language="typescript",
    )

    # Add TypeScript-specific constructs
    _parse_ts_extras(file_path, source, tree.root_node, chunks, relationships)

    return chunks, relationships


def _parse_ts_extras(
    file_path: str,
    source: bytes,
    root_node,
    chunks: list[CodeChunk],
    relationships: list[CodeRelationship],
) -> None:
    """Extract TypeScript-specific constructs: interfaces and enums."""
    for node in root_node.children:
        _process_ts_node(node, file_path, source, chunks, relationships)

        # Also check inside export statements
        if node.type in ("export_statement", "export_default_declaration"):
            for child in node.children:
                _process_ts_node(child, file_path, source, chunks, relationships)


def _process_ts_node(
    node,
    file_path: str,
    source: bytes,
    chunks: list[CodeChunk],
    relationships: list[CodeRelationship],
) -> None:
    """Process a single TypeScript-specific node."""
    if node.type == "interface_declaration":
        _parse_interface(node, file_path, source, chunks, relationships)
    elif node.type == "enum_declaration":
        _parse_enum(node, file_path, source, chunks, relationships)


def _parse_interface(
    node,
    file_path: str,
    source: bytes,
    chunks: list[CodeChunk],
    relationships: list[CodeRelationship],
) -> None:
    """Parse an interface_declaration into a class-like chunk."""
    name_node = _find_child_by_type(node, "type_identifier")
    if not name_node:
        return
    iface_name = _node_text(name_node, source)
    iface_text = _node_text(node, source)

    chunks.append(
        CodeChunk(
            text=iface_text,
            file_path=file_path,
            symbol_name=iface_name,
            symbol_type="class",
            language="typescript",
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            metadata={"kind": "interface"},
        )
    )

    # Check for extends clause on interface
    extends_clause = _find_child_by_type(node, "extends_type_clause")
    if extends_clause:
        for child in extends_clause.children:
            if child.type == "type_identifier":
                base_name = _node_text(child, source)
                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol=iface_name,
                        relationship="INHERITS",
                        target_file="",
                        target_symbol=base_name,
                    )
                )


def _parse_enum(
    node,
    file_path: str,
    source: bytes,
    chunks: list[CodeChunk],
    relationships: list[CodeRelationship],
) -> None:
    """Parse an enum_declaration into a class-like chunk."""
    name_node = _find_child_by_type(node, "identifier")
    if not name_node:
        return
    enum_name = _node_text(name_node, source)
    enum_text = _node_text(node, source)

    chunks.append(
        CodeChunk(
            text=enum_text,
            file_path=file_path,
            symbol_name=enum_name,
            symbol_type="class",
            language="typescript",
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            metadata={"kind": "enum"},
        )
    )
