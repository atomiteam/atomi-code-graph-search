"""Local SQLite full-text index. No network services or model downloads."""
import hashlib
import os
from pathlib import Path
import sqlite3

EXTENSIONS = {'.py', '.java', '.kt', '.go', '.rs', '.c', '.h', '.cpp', '.cc', '.hpp', '.js', '.jsx', '.ts', '.tsx', '.vue', '.php', '.sql', '.sh', '.bash', '.json', '.xml', '.yml', '.yaml', '.md', '.properties'}
SKIP = {'.git', '.venv', 'venv', 'node_modules', 'target', 'build', 'dist', '__pycache__', '.next', 'vendor', '.idea', '.gradle'}
MAX_BYTES = 1_000_000


def connect(path):
    db_path = Path(path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, root TEXT NOT NULL, digest TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS edges (root TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL, line INTEGER NOT NULL, PRIMARY KEY (root,source,target,kind,line))')
    db.execute('CREATE INDEX IF NOT EXISTS edges_target ON edges(target)')
    db.execute('CREATE TABLE IF NOT EXISTS calls (root TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL, line INTEGER NOT NULL, PRIMARY KEY (root,source,target,kind,line))')
    db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(path UNINDEXED, root UNINDEXED, line UNINDEXED, content, tokenize="unicode61")')
    return db


def iter_files(root, db_path):
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith('.'))
        for name in sorted(names):
            path = Path(folder, name)
            if path.suffix.lower() not in EXTENSIONS or path.resolve() == db_path:
                continue
            if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                continue
            yield path


def index(db, roots, db_path):
    counts = {'updated': 0, 'unchanged': 0, 'removed': 0}
    for input_root in roots:
        root = Path(input_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f'Not a directory: {root}')
        seen = set()
        with db:
            for path in iter_files(root, Path(db_path).expanduser().resolve()):
                key = str(path)
                seen.add(key)
                data = path.read_bytes()
                if b'\0' in data[:8192]:
                    continue
                digest = hashlib.sha256(data).hexdigest()
                existing = db.execute('SELECT digest FROM files WHERE path=?', (key,)).fetchone()
                if existing and existing[0] == digest:
                    counts['unchanged'] += 1
                    continue
                lines = data.decode('utf-8', errors='replace').splitlines()
                db.execute('DELETE FROM chunks WHERE path=?', (key,))
                # Line based chunks keep search results locatable.
                for start in range(0, len(lines), 30):
                    content = '\n'.join(lines[start:start + 30])
                    if content.strip():
                        db.execute('INSERT INTO chunks(path,root,line,content) VALUES (?,?,?,?)', (key, str(root), start + 1, content))
                db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?)', (key, str(root), digest))
                counts['updated'] += 1
            old = db.execute('SELECT path FROM files WHERE root=?', (str(root),)).fetchall()
            for (path,) in old:
                if path not in seen:
                    db.execute('DELETE FROM chunks WHERE path=?', (path,))
                    db.execute('DELETE FROM files WHERE path=?', (path,))
                    counts['removed'] += 1
            # Resolve imports against the complete set of indexed files, including unchanged files.
            from source_graph import rebuild
            rebuild(db, root)
    return counts


def search(db, query, limit=10):
    if not query.strip():
        return []
    # Treat user input as literal words, never as an FTS expression.
    import re
    terms = re.findall(r'\w+', query, flags=re.UNICODE)
    if not terms:
        return []
    expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms[:20])
    return [dict(path=p, line=n, snippet=s, rank=rank) for p, n, s, rank in db.execute(
        'SELECT path,line,snippet(chunks,3,"[","]","…",24),bm25(chunks) FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?',
        (expression, max(1, min(int(limit), 100))))]
