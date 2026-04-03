"""Python code parser using the ast module.

Delegates to the original parse_python_file() in indexer.py for consistency.
"""

from nullrealm.context.indexer import (
    CodeChunk,
    CodeRelationship,
    _extract_calls,
    _get_source_segment,
    parse_python_file,
)


def parse_file(file_path: str) -> tuple[list[CodeChunk], list[CodeRelationship]]:
    """Parse a Python file into code chunks and relationships."""
    return parse_python_file(file_path)


__all__ = [
    "CodeChunk",
    "CodeRelationship",
    "_extract_calls",
    "_get_source_segment",
    "parse_file",
]
