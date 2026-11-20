"""Local dashboard with asynchronous indexing and no external assets."""
from concurrent.futures import ThreadPoolExecutor
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

from local_index import connect, index, search
from source_graph import graph


class Dashboard(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, db_path):
        super().__init__(address, Handler)
        self.db_path = db_path
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.Lock()
        self.operation_lock = threading.Lock()
        self.jobs = {}

    def submit(self, paths):
        def task():
            for path in paths:
                with self.lock:
                    self.jobs[path] = {'status': 'indexing', 'detail': 'Scanning files…'}
                try:
                    with self.operation_lock:
                        with connect(self.db_path) as db:
                            registered = db.execute('SELECT 1 FROM repositories WHERE path=?', (path,)).fetchone()
                            if not registered:
                                continue
                            result = index(db, [path], self.db_path)
                    value = {'status': 'ready', 'detail': ', '.join(f'{k}: {v}' for k, v in result.items())}
                except Exception as exc:
                    value = {'status': 'error', 'detail': str(exc)}
                with self.lock:
                    self.jobs[path] = value
        with self.lock:
            for path in paths:
                self.jobs[path] = {'status': 'queued', 'detail': 'Waiting to index…'}
        self.pool.submit(task)

    def server_close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def _allowed(self):
        # Reject requests via alternate Host names and cross-origin form submissions.
        host = self.headers.get('Host', '')
        valid = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}',
                 f'[::1]:{self.server.server_port}'}
        if host not in valid:
            return False
        origin = self.headers.get('Origin')
        return not origin or urlparse(origin).netloc in valid and urlparse(origin).scheme == 'http'

    def _send(self, status, body, content_type):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._allowed():
            return self._send(403, 'Forbidden', 'text/plain')
        parsed = urlparse(self.path)
        with connect(self.server.db_path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS repositories(path TEXT PRIMARY KEY)')
            paths = [row[0] for row in db.execute('SELECT path FROM repositories ORDER BY path')]
            if parsed.path == '/api/status':
                with self.server.lock:
                    jobs = dict(self.server.jobs)
                repos = []
                for path in paths:
                    count = db.execute('SELECT COUNT(*) FROM files WHERE root=?', (path,)).fetchone()[0]
                    repos.append({'path': path, 'files': count, **jobs.get(path, {'status': 'ready' if count else 'not indexed', 'detail': ''})})
                return self._send(200, json.dumps(repos), 'application/json; charset=utf-8')
            if parsed.path == '/api/graph':
                selected = parse_qs(parsed.query).get('repo', [''])[0]
                if selected and selected not in paths:
                    return self._send(400, 'Unknown repository', 'text/plain')
                kind = parse_qs(parsed.query).get('type', ['imports'])[0]
                if kind not in ('imports', 'calls'):
                    return self._send(400, 'Unknown graph type', 'text/plain')
                return self._send(200, json.dumps(graph(db, selected or None, kind=kind)), 'application/json; charset=utf-8')
            if parsed.path == '/graph':
                return self._send(200, graph_page(paths), 'text/html; charset=utf-8')
            if parsed.path != '/':
                return self._send(404, 'Not found', 'text/plain')
            query = parse_qs(parsed.query).get('q', [''])[0][:200]
            results = search(db, query, 20) if query else []
        rows = ''.join(f'<tr><td><strong>{escape(Path(p).name)}</strong><small>{escape(p)}</small></td><td class="state" data-path="{escape(p, quote=True)}">Loading…</td><td><form method="post" action="/refresh"><input type="hidden" name="path" value="{escape(p, quote=True)}"><button>Refresh</button></form><form method="post" action="/remove" onsubmit="return confirm(\'Remove this repo from the index?\')"><input type="hidden" name="path" value="{escape(p, quote=True)}"><button class="subtle">Remove</button></form></td></tr>' for p in paths)
        matches = ''.join(f'<li><strong>{escape(r["path"])}:{r["line"]}</strong><pre>{escape(r["snippet"])}</pre></li>' for r in results)
        page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Atomi Code Graph Search</title><style>
:root{font-family:system-ui,sans-serif;color:#243047;background:#f6f8fb}*{box-sizing:border-box}main{max-width:1050px;margin:auto;padding:30px 18px}h1{margin-bottom:4px}p{color:#64748b}section{background:white;border:1px solid #e3e8f0;border-radius:14px;padding:22px;margin:22px 0;box-shadow:0 3px 14px #1d355708}form.inline,td form{display:inline-block;margin-right:6px}input{border:1px solid #cbd5e1;border-radius:8px;padding:10px;font:inherit;width:min(100%,540px)}button{border:0;border-radius:8px;background:#286ad1;color:white;padding:10px 15px;cursor:pointer;font-weight:600}.subtle{background:#e7edf5;color:#334155}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #edf1f5;padding:13px 8px;vertical-align:middle}td small{display:block;color:#64748b;word-break:break-all}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;padding:12px;border-radius:7px}li{margin:15px 0;overflow-wrap:anywhere}@media(max-width:700px){td{display:block}thead{display:none}tr{display:block;border-bottom:1px solid #ddd}}
</style><main><h1>Atomi Code Graph Search</h1><p>Browse and refresh code on this machine. <a href='/graph'>Explore source graph →</a></p><section><h2>Repositories</h2><form method="post" action="/add"><label for="path">Repository directory</label><br><input required id="path" name="path" placeholder="/home/me/projects/my-repo"> <button>Add and index</button></form><p>Enter a directory accessible to this computer.</p><form method="post" action="/refresh-all"><button class="subtle">Refresh all</button></form><table><thead><tr><th>Repository</th><th>Index status</th><th>Actions</th></tr></thead><tbody>''' + (rows or '<tr><td colspan="3">No repositories added yet.</td></tr>') + '''</tbody></table></section><section><h2>Search code</h2><form method="get" action="/"><input name="q" value="''' + escape(query, quote=True) + '''" placeholder="Class, endpoint, SQL table…"> <button>Search</button></form><ul>''' + matches + '''</ul></section></main><script>async function status(){try{const r=await fetch('/api/status');if(!r.ok)return;const data=await r.json();for(const x of data){for(const el of document.querySelectorAll('.state'))if(el.dataset.path===x.path)el.textContent=x.status+' · '+x.files+' files'+(x.detail?' · '+x.detail:'')}}catch(e){}}status();setInterval(status,1500)</script></html>'''
        self._send(200, page, 'text/html; charset=utf-8')

    def do_POST(self):
        if not self._allowed():
            return self._send(403, 'Forbidden', 'text/plain')
        if self.path not in ('/add', '/refresh', '/refresh-all', '/remove'):
            return self._send(404, 'Not found', 'text/plain')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 8192:
                raise ValueError('Form too large')
            data = parse_qs(self.rfile.read(length).decode('utf-8'))
            raw = data.get('path', [''])[0]
            with connect(self.server.db_path) as db:
                db.execute('CREATE TABLE IF NOT EXISTS repositories(path TEXT PRIMARY KEY)')
                paths = [row[0] for row in db.execute('SELECT path FROM repositories')]
                if self.path == '/add':
                    path = str(Path(raw).expanduser().resolve())
                    if not Path(path).is_dir():
                        raise ValueError('Directory does not exist')
                    db.execute('INSERT OR IGNORE INTO repositories VALUES (?)', (path,))
                    db.commit()
                    self.server.submit([path])
                elif self.path == '/refresh-all':
                    self.server.submit(paths)
                else:
                    if raw not in paths:
                        raise ValueError('Repository is not registered')
                    if self.path == '/refresh':
                        self.server.submit([raw])
                    else:
                        with self.server.operation_lock:
                            with db:
                                db.execute('DELETE FROM repositories WHERE path=?', (raw,))
                                db.execute('DELETE FROM edges WHERE root=?', (raw,))
                                db.execute('DELETE FROM calls WHERE root=?', (raw,))
                                db.execute('DELETE FROM chunks WHERE root=?', (raw,))
                                db.execute('DELETE FROM files WHERE root=?', (raw,))
                        with self.server.lock:
                            self.server.jobs.pop(raw, None)
        except (ValueError, UnicodeError) as exc:
            return self._send(400, str(exc), 'text/plain; charset=utf-8')
        self.send_response(303)
        self.send_header('Location', '/')
        self.send_header('Content-Length', '0')
        self.end_headers()


def serve(db_path, port=8080):
    server = Dashboard(('127.0.0.1', port), db_path)
    print(f'Dashboard: http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def graph_page(paths):
    options = ''.join(f'<option value="{escape(p, quote=True)}">{escape(Path(p).name)} · {escape(p)}</option>' for p in paths)
    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Source graph</title><style>body{font:15px system-ui,sans-serif;background:#f6f8fb;color:#243047;margin:25px}a{color:#286ad1}svg{width:100%;height:70vh;background:white;border:1px solid #d7dfe9;border-radius:10px}circle{fill:#2f75d6;cursor:pointer}circle.unresolved{fill:#d58a25}line{stroke:#a1afc4;stroke-width:1.5}text{font-size:11px;pointer-events:none}#detail{white-space:pre-wrap;overflow-wrap:anywhere}select{padding:9px;margin:12px}</style><h1>Source graph</h1><p><a href="/">← Dashboard</a> · Edges represent imports resolved to indexed files. Select a node to inspect its connections. Blue nodes are source functions; orange nodes are unresolved call sites.</p><label>Repository <select id="repo"><option value="">All repositories</option>""" + options + """</select></label><label>Graph <select id="type"><option value="imports">File imports</option><option value="calls">Call sites</option></select></label><div id="summary"></div><svg id="canvas" viewBox="0 0 1000 700" role="img" aria-label="File dependency graph"></svg><pre id="detail">Select a file node.</pre><script>
const svg=document.getElementById('canvas'),ns='http://www.w3.org/2000/svg';const el=(tag,attrs)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);svg.appendChild(e);return e};
async function draw(){const repo=document.getElementById('repo').value;const type=document.getElementById('type').value;const data=await(await fetch('/api/graph?repo='+encodeURIComponent(repo)+'&type='+type)).json();svg.replaceChildren();const nodes=data.nodes, edges=data.edges;document.getElementById('summary').textContent=nodes.length+' files · '+edges.length+' '+type+(data.truncated?' · Showing first 300 edges':'');if(!nodes.length){document.getElementById('detail').textContent='No graph edges yet. Add or refresh a repository with supported source files.';return}const pos=new Map(nodes.map((n,i)=>[n.id,{x:500+410*Math.cos(2*Math.PI*i/nodes.length),y:350+285*Math.sin(2*Math.PI*i/nodes.length)}]));for(const edge of edges){const a=pos.get(edge.source),b=pos.get(edge.target);el('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y})}for(const n of nodes){const p=pos.get(n.id);const dot=el('circle',{cx:p.x,cy:p.y,r:Math.max(5,Math.min(12,400/nodes.length)),class:n.id.includes('::?')?'unresolved':''});dot.addEventListener('click',()=>{const linked=edges.filter(e=>e.source===n.id||e.target===n.id);document.getElementById('detail').textContent=n.path+'\n'+linked.map(e=>(e.source===n.id?'→ '+e.target:'← '+e.source)+' ('+e.kind+', line '+e.line+')').join('\n')});const title=document.createElementNS(ns,'title');title.textContent=n.path;dot.appendChild(title);if(nodes.length<55)el('text',{x:p.x+8,y:p.y-8}).textContent=n.label}}document.getElementById('repo').addEventListener('change',draw);document.getElementById('type').addEventListener('change',draw);draw();</script></html>"""
