"""JavaScript/JSX code parser using tree-sitter."""

from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_javascript as ts_js
from tree_sitter import Language, Parser

from nullrealm.context.indexer import CodeChunk, CodeRelationship
from nullrealm.context.parsers.ecmascript_common import parse_ecmascript_tree

logger = logging.getLogger(__name__)

JS_LANGUAGE = Language(ts_js.language())
_parser = Parser(JS_LANGUAGE)


def parse_file(file_path: str) -> tuple[list[CodeChunk], list[CodeRelationship]]:
    """Parse a JavaScript/JSX file into code chunks and relationships."""
    path = Path(file_path)
    try:
        source = path.read_bytes()
    except OSError as exc:
        logger.warning("Skipping %s: %s", file_path, exc)
        return [], []

    try:
        tree = _parser.parse(source)
    except Exception as exc:
        logger.warning("Parse error in %s: %s", file_path, exc)
        return [], []

    return parse_ecmascript_tree(file_path, source, tree.root_node, language="javascript")
