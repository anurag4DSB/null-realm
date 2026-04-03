"""Multi-language code parser dispatcher.

Routes files to the appropriate tree-sitter or AST-based parser
based on file extension.
"""

import importlib
from pathlib import Path

from nullrealm.context.indexer import CodeChunk, CodeRelationship

EXTENSION_MAP = {
    ".py": "nullrealm.context.parsers.python_parser",
    ".js": "nullrealm.context.parsers.js_parser",
    ".jsx": "nullrealm.context.parsers.js_parser",
    ".ts": "nullrealm.context.parsers.ts_parser",
    ".tsx": "nullrealm.context.parsers.ts_parser",
    ".go": "nullrealm.context.parsers.go_parser",
}

SUPPORTED_EXTENSIONS = set(EXTENSION_MAP.keys())


def parse_file(file_path: str) -> tuple[list[CodeChunk], list[CodeRelationship]]:
    """Parse a source file into code chunks and relationships.

    Dispatches to the appropriate language parser based on file extension.
    Returns empty lists for unsupported extensions.
    """
    ext = Path(file_path).suffix
    module_name = EXTENSION_MAP.get(ext)
    if not module_name:
        return [], []
    module = importlib.import_module(module_name)
    return module.parse_file(file_path)
