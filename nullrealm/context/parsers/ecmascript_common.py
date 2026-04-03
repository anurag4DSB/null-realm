"""Shared ECMAScript parsing logic for JS and TS parsers.

Extracts functions, classes, imports, calls, and inheritance from
tree-sitter parse trees for JavaScript/TypeScript-family languages.
"""

from __future__ import annotations

import logging

from tree_sitter import Node

from nullrealm.context.indexer import CodeChunk, CodeRelationship

logger = logging.getLogger(__name__)


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


def _find_base_class_name(heritage_node: Node, source: bytes) -> str | None:
    """Extract the base class name from a class_heritage node.

    Handles both JS (class_heritage > identifier) and
    TS (class_heritage > extends_clause > identifier/type_identifier).
    """
    for child in heritage_node.children:
        if child.type in ("identifier", "type_identifier"):
            return _node_text(child, source)
        if child.type == "extends_clause":
            for grandchild in child.children:
                if grandchild.type in ("identifier", "type_identifier"):
                    return _node_text(grandchild, source)
    return None


def _collect_calls(node: Node, source: bytes) -> list[str]:
    """Recursively collect call_expression target names from a node."""
    calls: list[str] = []
    if node.type == "call_expression":
        func_node = node.children[0] if node.children else None
        if func_node:
            if func_node.type == "identifier":
                calls.append(_node_text(func_node, source))
            elif func_node.type == "member_expression":
                # e.g. obj.method() -> extract "method"
                prop = _find_child_by_type(func_node, "property_identifier")
                if prop:
                    calls.append(_node_text(prop, source))
    for child in node.children:
        calls.extend(_collect_calls(child, source))
    return calls


def parse_ecmascript_tree(
    file_path: str,
    source: bytes,
    root_node: Node,
    language: str,
) -> tuple[list[CodeChunk], list[CodeRelationship]]:
    """Parse an ECMAScript (JS/TS) tree-sitter tree into chunks and relationships.

    Handles function_declaration, class_declaration, variable declarations
    with arrow/function expressions, import_statement, and require() calls.
    """
    chunks: list[CodeChunk] = []
    relationships: list[CodeRelationship] = []

    # Collect module-level imports
    module_imports: list[str] = []

    for node in root_node.children:
        # --- Import statements (ES modules) ---
        if node.type == "import_statement":
            # Extract the module specifier (the string in quotes)
            string_node = _find_child_by_type(node, "string")
            if string_node:
                module_name = _node_text(string_node, source).strip("'\"")
                module_imports.append(module_name)
                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol="<module>",
                        relationship="IMPORTS",
                        target_file="",
                        target_symbol=module_name,
                    )
                )

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
                    language=language,
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

        # --- Class declarations ---
        elif node.type == "class_declaration":
            _parse_class(node, source, file_path, language, module_imports, chunks, relationships)

        # --- Variable declarations (arrow functions, function expressions, require) ---
        elif node.type in ("variable_declaration", "lexical_declaration"):
            for declarator in _find_children_by_type(node, "variable_declarator"):
                _parse_variable_declarator(
                    declarator, node, source, file_path, language,
                    module_imports, chunks, relationships,
                )

        # --- Export statements: unwrap the exported declaration ---
        elif node.type in ("export_statement", "export_default_declaration"):
            for child in node.children:
                if child.type == "function_declaration":
                    name_node = _find_child_by_type(child, "identifier")
                    if not name_node:
                        continue
                    func_name = _node_text(name_node, source)
                    func_text = _node_text(child, source)
                    calls = _collect_calls(child, source)

                    chunks.append(
                        CodeChunk(
                            text=func_text,
                            file_path=file_path,
                            symbol_name=func_name,
                            symbol_type="function",
                            language=language,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
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

                elif child.type == "class_declaration":
                    _parse_class(
                        child, source, file_path, language,
                        module_imports, chunks, relationships,
                    )

                elif child.type in ("variable_declaration", "lexical_declaration"):
                    for declarator in _find_children_by_type(child, "variable_declarator"):
                        _parse_variable_declarator(
                            declarator, child, source, file_path, language,
                            module_imports, chunks, relationships,
                        )

    return chunks, relationships


def _parse_class(
    node: Node,
    source: bytes,
    file_path: str,
    language: str,
    module_imports: list[str],
    chunks: list[CodeChunk],
    relationships: list[CodeRelationship],
) -> None:
    """Parse a class_declaration node into chunks and relationships."""
    # JS uses "identifier", TS uses "type_identifier" for class names
    name_node = _find_child_by_type(node, "identifier")
    if not name_node:
        name_node = _find_child_by_type(node, "type_identifier")
    if not name_node:
        return
    class_name = _node_text(name_node, source)
    class_text = _node_text(node, source)

    chunks.append(
        CodeChunk(
            text=class_text,
            file_path=file_path,
            symbol_name=class_name,
            symbol_type="class",
            language=language,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            imports=module_imports[:],
        )
    )

    # Check for extends clause (inheritance)
    # JS: class_heritage > identifier
    # TS: class_heritage > extends_clause > identifier/type_identifier
    heritage = _find_child_by_type(node, "class_heritage")
    if heritage:
        base_name = _find_base_class_name(heritage, source)
        if base_name:
            relationships.append(
                CodeRelationship(
                    source_file=file_path,
                    source_symbol=class_name,
                    relationship="INHERITS",
                    target_file="",
                    target_symbol=base_name,
                )
            )

    # Extract methods
    body = _find_child_by_type(node, "class_body")
    if body:
        for member in body.children:
            if member.type == "method_definition":
                method_name_node = _find_child_by_type(member, "property_identifier")
                if not method_name_node:
                    continue
                method_name = _node_text(method_name_node, source)
                full_name = f"{class_name}.{method_name}"
                method_text = _node_text(member, source)
                calls = _collect_calls(member, source)

                chunks.append(
                    CodeChunk(
                        text=method_text,
                        file_path=file_path,
                        symbol_name=full_name,
                        symbol_type="function",
                        language=language,
                        line_start=member.start_point[0] + 1,
                        line_end=member.end_point[0] + 1,
                        imports=module_imports[:],
                        metadata={"class": class_name},
                    )
                )

                relationships.append(
                    CodeRelationship(
                        source_file=file_path,
                        source_symbol=class_name,
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


def _parse_variable_declarator(
    declarator: Node,
    parent_node: Node,
    source: bytes,
    file_path: str,
    language: str,
    module_imports: list[str],
    chunks: list[CodeChunk],
    relationships: list[CodeRelationship],
) -> None:
    """Parse a variable_declarator that may contain a function expression or require()."""
    name_node = _find_child_by_type(declarator, "identifier")
    if not name_node:
        return
    var_name = _node_text(name_node, source)

    # Check if the value is an arrow_function or function_expression
    value_node = None
    for child in declarator.children:
        if child.type in ("arrow_function", "function_expression", "function"):
            value_node = child
            break

    if value_node:
        func_text = _node_text(parent_node, source)
        calls = _collect_calls(value_node, source)

        chunks.append(
            CodeChunk(
                text=func_text,
                file_path=file_path,
                symbol_name=var_name,
                symbol_type="function",
                language=language,
                line_start=parent_node.start_point[0] + 1,
                line_end=parent_node.end_point[0] + 1,
                imports=module_imports[:],
            )
        )
        for call_name in calls:
            relationships.append(
                CodeRelationship(
                    source_file=file_path,
                    source_symbol=var_name,
                    relationship="CALLS",
                    target_file="",
                    target_symbol=call_name,
                )
            )
        return

    # Check for require() calls — CommonJS imports
    for child in declarator.children:
        if child.type == "call_expression":
            func = child.children[0] if child.children else None
            if func and func.type == "identifier" and _node_text(func, source) == "require":
                args = _find_child_by_type(child, "arguments")
                if args:
                    for arg in args.children:
                        if arg.type == "string":
                            module_name = _node_text(arg, source).strip("'\"")
                            module_imports.append(module_name)
                            relationships.append(
                                CodeRelationship(
                                    source_file=file_path,
                                    source_symbol="<module>",
                                    relationship="IMPORTS",
                                    target_file="",
                                    target_symbol=module_name,
                                )
                            )
