"""Unified command line interface for the local code index."""
import argparse
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from local_index import connect, index, search

DEFAULT_DB = '~/.atomi-code-graph-search/index.sqlite3'


def state_dir(db_path):
    return Path(db_path).expanduser().resolve().parent


def register(db, paths):
    result = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f'Not a directory: {path}')
        db.execute('INSERT OR IGNORE INTO repositories(path) VALUES (?)', (str(path),))
        result.append(str(path))
    db.commit()
    return result


def repo_paths(db):
    return [r[0] for r in db.execute('SELECT path FROM repositories ORDER BY path')]


def resolve_repos(db, names):
    paths = repo_paths(db)
    selected = []
    for name in names:
        matched = [p for p in paths if p == str(Path(name).expanduser().resolve()) or Path(p).name == name]
        if not matched:
            raise ValueError(f'Unknown repository: {name}. Use "atomi-code-graph-search repos" to list registered paths.')
        if len(matched) > 1:
            raise ValueError(f'Ambiguous repository name: {name}. Use its full path.')
        if matched[0] not in selected:
            selected.append(matched[0])
    return selected


def pid_file(db_path):
    return state_dir(db_path) / ('mcp-' + hashlib.sha256(str(Path(db_path).expanduser().resolve()).encode()).hexdigest()[:12] + '.pid')


def running_pid(db_path):
    path = pid_file(db_path)
    try:
        pid = int(path.read_text().strip())
        argv = Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace').split('\0')
        if '-m' in argv and 'cli' in argv and '_serve' in argv and str(Path(db_path).expanduser().resolve()) in argv:
            return pid
    except (FileNotFoundError, ValueError, PermissionError, ProcessLookupError):
        pass
    return None


def start_mcp(db_path, port):
    if running_pid(db_path):
        print(f'MCP already running (PID {running_pid(db_path)}).')
        return
    path = pid_file(db_path)
    path.unlink(missing_ok=True)
    log = state_dir(db_path) / 'mcp.log'
    with log.open('ab') as output:
        process = subprocess.Popen(
            [sys.executable, '-m', 'cli', '--db', str(Path(db_path).expanduser().resolve()), '_serve', '--port', str(port)],
            cwd=str(Path(__file__).resolve().parent), stdin=subprocess.DEVNULL,
            stdout=output, stderr=output, start_new_session=True,
        )
    time.sleep(0.5)
    if process.poll() is not None:
        raise RuntimeError(f'MCP exited during startup. See {log}')
    path.write_text(str(process.pid))
    print(f'MCP running at http://127.0.0.1:{port}/mcp (PID {process.pid}); log: {log}')


def stop_mcp(db_path):
    pid = running_pid(db_path)
    if pid is None:
        print('No managed MCP server is running.')
        pid_file(db_path).unlink(missing_ok=True)
        return
    os.kill(pid, signal.SIGTERM)
    pid_file(db_path).unlink(missing_ok=True)
    print(f'Stopped MCP server (PID {pid}).')


def web_pid_file(db_path):
    digest = hashlib.sha256(str(Path(db_path).expanduser().resolve()).encode()).hexdigest()[:12]
    return state_dir(db_path) / f'web-{digest}.pid'


def managed_pid(db_path, service):
    path = web_pid_file(db_path) if service == 'web' else pid_file(db_path)
    try:
        pid = int(path.read_text())
        argv = Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace').split('\0')
        marker = '_webserve' if service == 'web' else '_serve'
        if '-m' in argv and 'cli' in argv and marker in argv and str(Path(db_path).expanduser().resolve()) in argv:
            return pid
    except (FileNotFoundError, ValueError, PermissionError, ProcessLookupError):
        pass
    return None


def start_web(db_path, port):
    if not 1 <= port <= 65535:
        raise ValueError('Port must be between 1 and 65535')
    pid = managed_pid(db_path, 'web')
    if pid:
        print(f'Web dashboard already running (PID {pid}).')
        return
    path = web_pid_file(db_path)
    path.unlink(missing_ok=True)
    state_dir(db_path).mkdir(parents=True, exist_ok=True)
    log = state_dir(db_path) / 'web.log'
    with log.open('ab') as output:
        process = subprocess.Popen(
            [sys.executable, '-m', 'cli', '--db', str(Path(db_path).expanduser().resolve()), '_webserve', '--port', str(port)],
            cwd=str(Path(__file__).resolve().parent), stdin=subprocess.DEVNULL,
            stdout=output, stderr=output, start_new_session=True)
    time.sleep(0.5)
    if process.poll() is not None:
        raise RuntimeError(f'Web server exited during startup. See {log}')
    path.write_text(str(process.pid))
    print(f'Web dashboard: http://127.0.0.1:{port} (PID {process.pid})')


def stop_web(db_path):
    pid = managed_pid(db_path, 'web')
    if pid:
        os.kill(pid, signal.SIGTERM)
        print(f'Stopped web dashboard (PID {pid}).')
    else:
        print('No managed web dashboard is running.')
    web_pid_file(db_path).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='atomi-code-graph-search', description='Index and search local repositories')
    parser.add_argument('--db', default=os.environ.get('CODE_INTEL_DB', DEFAULT_DB))
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add', help='Register local repositories and index them')
    add.add_argument('paths', nargs='+')
    remove = commands.add_parser('remove', help='Unregister repositories and delete their indexed content')
    remove.add_argument('repositories', nargs='+')
    commands.add_parser('repos', help='List registered repositories')
    refresh = commands.add_parser('refresh', help='Refresh all or selected registered repositories')
    refresh.add_argument('repositories', nargs='*', help='Names or full paths; empty means all')
    graph_cmd = commands.add_parser('graph', help='Export file dependency graph')
    graph_cmd.add_argument('--type', choices=('imports', 'calls'), default='imports')
    graph_cmd.add_argument('--repo', help='Registered name or full path; defaults to all')
    graph_cmd.add_argument('--format', choices=('json', 'dot'), default='dot')
    graph_cmd.add_argument('--limit', type=int, default=300)
    find = commands.add_parser('search', help='Search indexed source')
    find.add_argument('query')
    find.add_argument('--limit', type=int, default=10)
    mcp_cmd = commands.add_parser('mcp', help='Manage MCP server')
    mcp_commands = mcp_cmd.add_subparsers(dest='action', required=True)
    mcp_start = mcp_commands.add_parser('start', help='Start local HTTP MCP in the background')
    mcp_start.add_argument('--port', type=int, default=8765)
    mcp_commands.add_parser('stop', help='Stop server started by this CLI')
    mcp_commands.add_parser('status', help='Show managed server status')
    mcp_commands.add_parser('stdio', help='Run stdio MCP in the foreground for an MCP client')
    web = commands.add_parser('web', help='Manage browser dashboard')
    web_commands = web.add_subparsers(dest='action', required=True)
    web_start = web_commands.add_parser('start', help='Start dashboard in background')
    web_start.add_argument('--port', type=int, default=8080)
    web_commands.add_parser('stop', help='Stop dashboard')
    web_commands.add_parser('status', help='Show dashboard status')
    web_run = web_commands.add_parser('run', help='Run dashboard in foreground')
    web_run.add_argument('--port', type=int, default=8080)
    web_hidden = commands.add_parser('_webserve', help=argparse.SUPPRESS)
    web_hidden.add_argument('--port', type=int, required=True)
    hidden = commands.add_parser('_serve', help=argparse.SUPPRESS)
    hidden.add_argument('--port', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == '_webserve' or args.command == 'web' and args.action == 'run':
            from web_server import serve
            serve(args.db, args.port)
            return 0
        if args.command == '_serve':
            from mcp_server import make_server
            make_server(args.db, args.port).run(transport='streamable-http')
            return 0
        if args.command == 'web' and args.action in ('start', 'stop', 'status'):
            if args.action == 'start':
                start_web(args.db, args.port)
            elif args.action == 'stop':
                stop_web(args.db)
            else:
                pid = managed_pid(args.db, 'web')
                print(f'Web dashboard running (PID {pid}).' if pid else 'Web dashboard stopped.')
            return 0
        if args.command == 'mcp' and args.action == 'stdio':
            from mcp_server import make_server
            make_server(args.db).run(transport='stdio')
            return 0
        with connect(args.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS repositories(path TEXT PRIMARY KEY)')
            if args.command == 'add':
                paths = register(db, args.paths)
                print(f'Registered: {", ".join(paths)}')
                print(index(db, paths, args.db))
            elif args.command == 'repos':
                print('\n'.join(repo_paths(db)) or 'No repositories registered.')
            elif args.command == 'refresh':
                paths = resolve_repos(db, args.repositories) if args.repositories else repo_paths(db)
                if paths:
                    print(index(db, paths, args.db))
                else:
                    print('No repositories registered. Use "atomi-code-graph-search add /path/to/repo".')
            elif args.command == 'remove':
                paths = resolve_repos(db, args.repositories)
                with db:
                    for path in paths:
                        db.execute('DELETE FROM edges WHERE root=?', (path,))
                        db.execute('DELETE FROM calls WHERE root=?', (path,))
                        db.execute('DELETE FROM chunks WHERE root=?', (path,))
                        db.execute('DELETE FROM files WHERE root=?', (path,))
                        db.execute('DELETE FROM repositories WHERE path=?', (path,))
                print(f'Removed: {", ".join(paths)}')
            elif args.command == 'graph':
                import json
                from source_graph import graph, to_dot
                root = resolve_repos(db, [args.repo])[0] if args.repo else None
                data = graph(db, root, max(1, min(args.limit, 1000)), args.type)
                print(json.dumps(data, indent=2) if args.format == 'json' else to_dot(data))
            elif args.command == 'search':
                for hit in search(db, args.query, args.limit):
                    print(f"{hit['path']}:{hit['line']}\n  {hit['snippet']}\n")
            elif args.command == 'mcp':
                if args.action == 'start':
                    if not 1 <= args.port <= 65535:
                        raise ValueError('Port must be between 1 and 65535')
                    start_mcp(args.db, args.port)
                elif args.action == 'stop':
                    stop_mcp(args.db)
                else:
                    pid = running_pid(args.db)
                    print(f'MCP running (PID {pid}).' if pid else 'MCP stopped.')
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    sys.exit(main())
