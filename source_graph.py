"""File imports and conservative local call graph extraction."""
import ast
import json
from pathlib import Path
import re

SCRIPT = {'.js', '.jsx', '.ts', '.tsx', '.vue'}
RELATIVE_IMPORT = re.compile(r'''(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)["'](\.[^"']+)["']''')
JAVA_IMPORT = re.compile(r'^\s*import\s+(?:static\s+)?([\w.]+)\s*;', re.MULTILINE)


def resolve(base, value, known, extensions):
    candidate = (base / value).resolve()
    for path in [candidate, *(candidate.with_suffix(e) for e in extensions),
                 *(candidate / ('index' + e) for e in extensions), candidate / '__init__.py']:
        if str(path) in known:
            return str(path)
    return None


def python_calls(path, text, root, known):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], []
    imports = []
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = Path(root) if not node.level else Path(path).parent
            if node.level:
                for _ in range(node.level - 1):
                    base = base.parent
            module = (node.module or '').replace('.', '/')
            dest = resolve(base, module, known, ('.py',)) if module else None
            for alias in node.names:
                target = dest or resolve(base, str(Path(module) / alias.name), known, ('.py',))
                if target and target != path:
                    imports.append((target, 'Python import', node.lineno))
                    aliases[alias.asname or alias.name] = (target, alias.name if target == dest else '')
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target = resolve(Path(root), alias.name.replace('.', '/'), known, ('.py',))
                if target and target != path:
                    imports.append((target, 'Python import', node.lineno))
                    aliases[alias.asname or alias.name.split('.')[0]] = (target, '')
    defs = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(node.name, []).append(node)
    calls = set()
    for fn_list in defs.values():
        for fn in fn_list:
            source = f'{path}::{fn.name}@{fn.lineno}'
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                call = node.func
                if isinstance(call, ast.Name):
                    if len(defs.get(call.id, [])) == 1:
                        target_node = defs[call.id][0]
                        calls.add((source, f'{path}::{call.id}@{target_node.lineno}', 'Python local call', node.lineno))
                    elif call.id in aliases and aliases[call.id][1]:
                        dest, name = aliases[call.id]
                        calls.add((source, f'{dest}::{name}', 'Python imported call (name only)', node.lineno))
                elif isinstance(call, ast.Attribute) and isinstance(call.value, ast.Name):
                    alias = aliases.get(call.value.id)
                    if alias and not alias[1]:
                        calls.add((source, f'{alias[0]}::{call.attr}', 'Python imported call (name only)', node.lineno))
    return sorted(set(imports)), sorted(calls)


def extract(path, text, known, root):
    file = Path(path)
    if file.suffix == '.py':
        return python_calls(path, text, root, known)
    imports = set()
    if file.suffix in SCRIPT:
        for match in RELATIVE_IMPORT.finditer(text):
            dest = resolve(file.parent, match.group(1), known, tuple(SCRIPT))
            if dest and dest != path:
                imports.add((dest, 'Relative import', text.count('\n', 0, match.start()) + 1))
    elif file.suffix == '.java':
        for match in JAVA_IMPORT.finditer(text):
            target = match.group(1).replace('.', '/') + '.java'
            matches = [p for p in known if p.endswith('/' + target) and p.startswith(str(root) + '/')]
            if len(matches) == 1 and matches[0] != path:
                imports.add((matches[0], 'Java import', text.count('\n', 0, match.start()) + 1))
    return sorted(imports), []


def rebuild(db, root):
    root = str(Path(root).resolve())
    from call_parser import LANGUAGES, calls_in_file
    paths = {p for (p,) in db.execute('SELECT path FROM files WHERE root=?', (root,))}
    with db:
        db.execute('DELETE FROM edges WHERE root=?', (root,))
        db.execute('DELETE FROM calls WHERE root=?', (root,))
        for path in sorted(paths):
            if Path(path).suffix not in LANGUAGES:
                continue
            try:
                text = Path(path).read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            imports, _ = extract(path, text, paths, root)
            calls = calls_in_file(path, text)
            if Path(path).suffix == '.py':
                _, imported = python_calls(path, text, root, paths)
                imported = [e for e in imported if 'imported call' in e[2]]
                located = {(e[0], e[3]) for e in imported}
                calls = [e for e in calls if not (e[0], e[3]) in located or 'unresolved' not in e[2]] + imported
            for dest, kind, line in imports:
                db.execute('INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?)', (root, path, dest, kind, line))
            for source, target, kind, line in calls:
                db.execute('INSERT OR IGNORE INTO calls VALUES (?,?,?,?,?)', (root, source, target, kind, line))


def graph(db, root=None, limit=300, kind='imports'):
    table = 'calls' if kind == 'calls' else 'edges'
    roots = [root] if root else [r[0] for r in db.execute('SELECT DISTINCT root FROM files ORDER BY root')]
    edges = []
    for repo in roots:
        edges.extend(dict(root=r, source=s, target=t, kind=k, line=n) for r, s, t, k, n in
                     db.execute(f'SELECT root,source,target,kind,line FROM {table} WHERE root=? ORDER BY source,target LIMIT ?', (repo, limit)))
    edges = edges[:limit]
    nodes = sorted({p for e in edges for p in (e['source'], e['target'])})
    return {'nodes': [{'id': p, 'label': p.split('::')[-1] if '::' in p else Path(p).name, 'path': p} for p in nodes], 'edges': edges, 'truncated': len(edges) >= limit, 'type': kind}


def to_dot(data):
    lines = ['digraph source {']
    for node in data['nodes']:
        lines.append(f'  {json.dumps(node["id"])} [label={json.dumps(node["label"])}];')
    for edge in data['edges']:
        lines.append(f'  {json.dumps(edge["source"])} -> {json.dumps(edge["target"])} [label={json.dumps(edge["kind"])}];')
    return '\n'.join(lines + ['}'])
