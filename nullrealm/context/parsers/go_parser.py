"""Go code parser using tree-sitter.

Extracts functions, methods, structs, interfaces, imports, calls,
and struct embedding relationships from Go source files.
"""

from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_go as ts_go
from tree_sitter import Language, Node, Parser

from nullrealm.context.indexer import CodeChunk, CodeRelationship

logger = logging.getLogger(__name__)

GO_LANGUAGE = Language(ts_go.language())
_parser = Parser(GO_LANGUAGE)


def _node_text(node: Node, source: bytes) -> str:
    """Extract the UTF-8 text for a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _find_child_by_type(node: Node, type_name: str) -> Node | None:
    """Find the first direct child with the given type."""
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _find_children_by_type(node: Node, type_name: str) -> list[Node]:
    """Find all direct children with the given type."""
    return [child for child in node.children if child.type == type_name]


def _collect_calls(node: Node, source: bytes) -> list[str]:
    """Recursively collect call_expression target names from a node."""
    calls: list[str] = []
    if node.type == "call_expression":
        func_node = node.children[0] if node.children else None
        if func_node:
            if func_node.type == "identifier":
                calls.append(_node_text(func_node, source))
            elif func_node.type == "selector_expression":
                # e.g. obj.Method() -> extract "Method"
                field = _find_child_by_type(func_node, "field_identifier")
                if field:
                    calls.append(_node_text(field, source))
    for child in node.children:
        calls.extend(_collect_calls(child, source))
    return calls


def _extract_receiver_type(node: Node, source: bytes) -> str | None:
    """Extract the receiver type name from a method_declaration.

    Handles both value receivers `(s Server)` and pointer receivers `(s *Server)`.
    """
    params = _find_child_by_type(node, "parameter_list")
    if not params:
        return None
    for param in params.children:
        if param.type == "parameter_declaration":
            # Look for type_identifier directly or inside pointer_type
            type_id = _find_child_by_type(param, "type_identifier")
            if type_id:
                return _node_text(type_id, source)
            pointer = _find_child_by_type(param, "pointer_type")
            if pointer:
                type_id = _find_child_by_type(pointer, "type_identifier")
                if type_id:
                    return _node_text(type_id, source)
    return None


def parse_file(file_path: str) -> tuple[list[CodeChunk], list[CodeRelationship]]:
    """Parse a Go file into code chunks and relationships."""
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

    chunks: list[CodeChunk] = []
    relationships: list[CodeRelationship] = []
    module_imports: list[str] = []

    for node in tree.root_node.children:
        # --- Import declarations ---
        if node.type == "import_declaration":
            _parse_imports(node, source, file_path, module_imports, relationships)

        # --- Function declarations ---
        elif node.type == "function_declaration":
            name_node = _find_child_by_type(node, "identifier")
            if not name_node:
                continue
            func_name = _node_text(name_node, source)
            func_text = _node_text(node, source)
            calls = _collect_calls(node, source)

            chunks.append(
                CodeChunk(
                    text=func_text,
                    file_path=file_path,
                    symbol_name=func_name,
                    symbol_type="function",
                    language="go",
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    imports=module_imports[:],
                )
            )
            for call_name in calls:
                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol=func_name,
                        relationship="CALLS",
                        target_file="",
                        target_symbol=call_name,
                    )
                )

        # --- Method declarations ---
        elif node.type == "method_declaration":
            name_node = _find_child_by_type(node, "field_identifier")
            if not name_node:
                continue
            method_name = _node_text(name_node, source)
            receiver_type = _extract_receiver_type(node, source)
            full_name = f"{receiver_type}.{method_name}" if receiver_type else method_name
            method_text = _node_text(node, source)
            calls = _collect_calls(node, source)

            chunks.append(
                CodeChunk(
                    text=method_text,
                    file_path=file_path,
                    symbol_name=full_name,
                    symbol_type="function",
                    language="go",
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    imports=module_imports[:],
                    metadata={"receiver_type": receiver_type} if receiver_type else {},
                )
            )

            if receiver_type:
                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol=receiver_type,
                        relationship="CONTAINS",
                        target_file=file_path,
                        target_symbol=full_name,
                    )
                )

            for call_name in calls:
                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol=full_name,
                        relationship="CALLS",
                        target_file="",
                        target_symbol=call_name,
                    )
                )

        # --- Type declarations (structs and interfaces) ---
        elif node.type == "type_declaration":
            _parse_type_declaration(node, source, file_path, module_imports, chunks, relationships)

    return chunks, relationships


def _parse_imports(
    node: Node,
    source: bytes,
    file_path: str,
    module_imports: list[str],
    relationships: list[CodeRelationship],
) -> None:
    """Parse an import_declaration into import relationships."""
    # Single import: import "fmt"
    # Grouped import: import ( "fmt" \n "os" )
    for child in node.children:
        if child.type == "import_spec":
            _process_import_spec(child, source, file_path, module_imports, relationships)
        elif child.type == "import_spec_list":
            for spec in child.children:
                if spec.type == "import_spec":
                    _process_import_spec(spec, source, file_path, module_imports, relationships)


def _process_import_spec(
    spec: Node,
    source: bytes,
    file_path: str,
    module_imports: list[str],
    relationships: list[CodeRelationship],
) -> None:
    """Process a single import_spec node."""
    path_node = _find_child_by_type(spec, "interpreted_string_literal")
    if not path_node:
        return
    import_path = _node_text(path_node, source).strip('"')
    module_imports.append(import_path)
    relationships.append(
        CodeRelationship(
            source_file=file_path,
            source_symbol="<module>",
            relationship="IMPORTS",
            target_file="",
            target_symbol=import_path,
        )
    )


def _parse_type_declaration(
    node: Node,
    source: bytes,
    file_path: str,
    module_imports: list[str],
    chunks: list[CodeChunk],
    relationships: list[CodeRelationship],
) -> None:
    """Parse a type_declaration which may contain struct_type or interface_type."""
    for child in node.children:
        if child.type == "type_spec":
            _parse_type_spec(child, node, source, file_path, module_imports, chunks, relationships)


def _parse_type_spec(
    spec: Node,
    decl_node: Node,
    source: bytes,
    file_path: str,
    module_imports: list[str],
    chunks: list[CodeChunk],
    relationships: list[CodeRelationship],
) -> None:
    """Parse a type_spec within a type_declaration."""
    name_node = _find_child_by_type(spec, "type_identifier")
    if not name_node:
        return
    type_name = _node_text(name_node, source)

    struct_type = _find_child_by_type(spec, "struct_type")
    iface_type = _find_child_by_type(spec, "interface_type")

    if struct_type:
        struct_text = _node_text(decl_node, source)
        chunks.append(
            CodeChunk(
                text=struct_text,
                file_path=file_path,
                symbol_name=type_name,
                symbol_type="class",
                language="go",
                line_start=decl_node.start_point[0] + 1,
                line_end=decl_node.end_point[0] + 1,
                imports=module_imports[:],
                metadata={"kind": "struct"},
            )
        )

        # Check for embedded structs (anonymous fields = inheritance)
        field_list = _find_child_by_type(struct_type, "field_declaration_list")
        if field_list:
            for field_decl in _find_children_by_type(field_list, "field_declaration"):
                # An embedded field has a type but no field name
                # It appears as a field_declaration with only a type_identifier child
                children_types = [c.type for c in field_decl.children]
                has_field_name = "field_identifier" in children_types
                if not has_field_name:
                    # Look for the type name (embedded)
                    embedded_type = _find_child_by_type(field_decl, "type_identifier")
                    if embedded_type:
                        embedded_name = _node_text(embedded_type, source)
                        relationships.append(
                            CodeRelationship(
                                source_file=file_path,
                                source_symbol=type_name,
                                relationship="INHERITS",
                                target_file="",
                                target_symbol=embedded_name,
                            )
                        )
                    # Also check pointer to embedded type: *BaseType
                    pointer = _find_child_by_type(field_decl, "pointer_type")
                    if pointer:
                        embedded_type = _find_child_by_type(pointer, "type_identifier")
                        if embedded_type:
                            embedded_name = _node_text(embedded_type, source)
                            relationships.append(
                                CodeRelationship(
                                    source_file=file_path,
                                    source_symbol=type_name,
                                    relationship="INHERITS",
                                    target_file="",
                                    target_symbol=embedded_name,
                                )
                            )

    elif iface_type:
        iface_text = _node_text(decl_node, source)
        chunks.append(
            CodeChunk(
                text=iface_text,
                file_path=file_path,
                symbol_name=type_name,
                symbol_type="class",
                language="go",
                line_start=decl_node.start_point[0] + 1,
                line_end=decl_node.end_point[0] + 1,
                imports=module_imports[:],
                metadata={"kind": "interface"},
            )
        )
