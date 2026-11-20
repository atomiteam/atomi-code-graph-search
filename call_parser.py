"""Syntax-backed call sites for nine languages. Only unique direct local calls resolve."""
from pathlib import Path

from tree_sitter_language_pack import get_parser

LANGUAGES = {
    '.c': 'c', '.h': 'cpp', '.cpp': 'cpp', '.cc': 'cpp', '.hpp': 'cpp',
    '.java': 'java', '.js': 'javascript', '.jsx': 'javascript',
    '.ts': 'typescript', '.tsx': 'tsx', '.sh': 'bash', '.bash': 'bash',
    '.rs': 'rust', '.go': 'go', '.py': 'python', '.php': 'php',
}
DEFINITIONS = {
    'c': {'function_definition'}, 'cpp': {'function_definition'},
    'java': {'method_declaration', 'constructor_declaration'},
    'javascript': {'function_declaration', 'method_definition', 'variable_declarator'},
    'typescript': {'function_declaration', 'method_definition', 'variable_declarator'},
    'tsx': {'function_declaration', 'method_definition', 'variable_declarator'},
    'bash': {'function_definition'}, 'rust': {'function_item'},
    'go': {'function_declaration', 'method_declaration'},
    'python': {'function_definition', 'async_function_definition'},
    'php': {'function_definition', 'method_declaration'},
}
CALLS = {
    'c': {'call_expression'}, 'cpp': {'call_expression'},
    'java': {'method_invocation', 'object_creation_expression'},
    'javascript': {'call_expression'}, 'typescript': {'call_expression'},
    'tsx': {'call_expression'}, 'bash': {'command'},
    'rust': {'call_expression', 'method_call_expression'},
    'go': {'call_expression'}, 'python': {'call'},
    'php': {'function_call_expression', 'member_call_expression', 'scoped_call_expression'},
}


def name_of(node, language):
    field = node.child_by_field_name('name')
    if field is None and language in ('c', 'cpp'):
        field = node.child_by_field_name('declarator')
        while field and field.type not in ('identifier', 'field_identifier', 'operator_name'):
            field = field.child_by_field_name('declarator')
    return field.text.decode('utf-8', errors='replace') if field else None


def call_of(node, language):
    field = node.child_by_field_name('function') or node.child_by_field_name('name')
    if language == 'bash':
        field = node.child_by_field_name('name')
    if field is None:
        return None, False
    # A qualified expression can be overloaded, virtual, dynamic, or external.
    direct = field.type in ('identifier', 'name', 'simple_identifier', 'command_name', 'variable_name')
    raw = field.text.decode('utf-8', errors='replace')
    return raw, direct


def calls_in_file(path, text):
    language = LANGUAGES.get(Path(path).suffix.lower())
    if not language:
        return []
    data = text.encode('utf-8')
    tree = get_parser(language).parse(data)
    definitions = {}
    sites = []

    def visit(node, owner=None):
        if node.type in DEFINITIONS[language]:
            value = node.child_by_field_name('value') if node.type == 'variable_declarator' else None
            name = name_of(node, language) if node.type != 'variable_declarator' or value and value.type in ('arrow_function', 'function_expression', 'function') else None

            if name:
                owner = f'{path}::{name}@{node.start_point.row + 1}'
                definitions.setdefault(name, []).append(owner)
        if node.type in CALLS[language]:
            callee, direct = call_of(node, language)
            if callee:
                sites.append((owner or f'{path}::<module>@1', callee, direct, node.start_point.row + 1))
        for child in node.named_children:
            visit(child, owner)

    visit(tree.root_node)
    edges = set()
    for source, callee, direct, line in sites:
        matches = definitions.get(callee, []) if direct else []
        if len(matches) == 1:
            edges.add((source, matches[0], f'{language} local call', line))
        else:
            # Distinct node per call site; no invented link to a definition.
            edges.add((source, f'{path}::?{callee}@{line}', f'{language} unresolved call', line))
    return sorted(edges)
