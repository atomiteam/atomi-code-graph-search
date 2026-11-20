"""MCP tools backed by the local SQLite index."""
import os
from mcp.server.fastmcp import FastMCP
from local_index import connect, search
from source_graph import graph


def make_server(db_path='~/.atomi-code-graph-search/index.sqlite3', port=8765):
    mcp = FastMCP('atomi-code-graph-search', host='127.0.0.1', port=port)

    @mcp.tool()
    def search_code(query: str, limit: int = 10) -> list[dict]:
        """Search local source code and return paths, line numbers and snippets."""
        with connect(db_path) as db:
            return search(db, query, limit)

    @mcp.tool()
    def list_repositories() -> list[str]:
        """List indexed repository paths."""
        with connect(db_path) as db:
            return [row[0] for row in db.execute('SELECT DISTINCT root FROM files ORDER BY root')]

    @mcp.tool()
    def source_graph(repo: str = '', kind: str = 'imports', limit: int = 100) -> dict:
        """Get import edges or call-site edges for an indexed repository path."""
        if kind not in ('imports', 'calls'):
            raise ValueError('kind must be imports or calls')
        with connect(db_path) as db:
            return graph(db, repo or None, max(1, min(limit, 300)), kind)

    return mcp


if __name__ == '__main__':
    make_server(os.environ.get('CODE_INTEL_DB', '~/.atomi-code-graph-search/index.sqlite3')).run()
