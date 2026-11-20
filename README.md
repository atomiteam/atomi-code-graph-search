# Atomi Code Graph Search

Index and search repositories on your machine. The default command uses Python and SQLite full-text search; no account, server, API key, model download, or cloud service is required. Search uses keywords; import and call graphs use static parsing. Semantic search is not included.

## Install

Requires Python 3.10+ with SQLite FTS5. From this directory:

```sh
python -m pip install -e .
```

For MCP support, install the optional dependency instead. Run this command from the repository directory:

**Windows Command Prompt or PowerShell**

```bat
python -m pip install -e ".[mcp]"
```

**Linux or macOS**

```sh
python -m pip install -e '.[mcp]'
```

Windows Command Prompt does not treat single quotes as argument quotes. The pip upgrade notice is informational; upgrading pip is not required for this installation.

After pulling new commits, rerun `python -m pip install -e ".[mcp]"` in the repository directory before restarting the dashboard. An editable install picks up source edits immediately, but pip must install new dependencies declared in `pyproject.toml` (such as `psutil`) separately. Use `python -m pip show psutil` to verify that the Python interpreter running the CLI has it.

## Browser dashboard

After installing the CLI, launch the unauthenticated dashboard:

```sh
atomi-code-graph-search web start
# Open http://127.0.0.1:8080
atomi-code-graph-search web status
atomi-code-graph-search web stop
```

Use `atomi-code-graph-search web start --port 9000` for another port, or `atomi-code-graph-search web run` to run in the foreground. The page lets you add a repository by its local directory path, see file counts and queued/indexing/ready/error states, refresh one or all repositories, remove registrations, and search code. Indexing happens in a background queue; the page shows files discovered, indexing progress, and graph construction progress. Refresh the page for new search results after indexing finishes. After upgrading, restart an already running dashboard with `atomi-code-graph-search web stop` followed by `atomi-code-graph-search web start`.

The dashboard has **no authentication** and listens only on localhost. Anyone able to access your local browser or this host's loopback port can use it, including adding paths that the server process can read. Do not publish or proxy its port to the Internet. The browser page and scripts are served by this package; no external assets are loaded.

## Commands

| Action | Command |
| --- | --- |
| Add and immediately index a local repository | `atomi-code-graph-search add /path/to/repo` |
| Add several repositories | `atomi-code-graph-search add /path/to/repo-a /path/to/repo-b` |
| List registered repositories | `atomi-code-graph-search repos` |
| Refresh all registered repositories | `atomi-code-graph-search refresh` |
| Refresh one repository | `atomi-code-graph-search refresh repo-a` |
| Refresh several repositories | `atomi-code-graph-search refresh repo-a repo-b` |
| Search indexed code | `atomi-code-graph-search search "device registration"` |
| Remove a repository and its index | `atomi-code-graph-search remove repo-a` |
| Start a localhost web dashboard | `atomi-code-graph-search web start` |
| Stop the web dashboard | `atomi-code-graph-search web stop` |
| Start a localhost HTTP MCP server | `atomi-code-graph-search mcp start` |
| Check the managed server | `atomi-code-graph-search mcp status` |
| Stop the managed server | `atomi-code-graph-search mcp stop` |
| Run stdio MCP for an MCP client | `atomi-code-graph-search mcp stdio` |

Use a full path when two registered repositories have the same directory name. `refresh` indexes changed files, skips unchanged files, and removes deleted files. `remove` deletes only the local index and registration, **never the repository**. Use `atomi-code-graph-search --db /path/to/index.sqlite3 ...` to select a separate index. The default is `~/.atomi-code-graph-search/index.sqlite3`.

The HTTP server listens only on `127.0.0.1:8765` at `/mcp`; change its port with `atomi-code-graph-search mcp start --port 9000`. It runs in the background and writes `~/.atomi-code-graph-search/mcp.log`. The `stop` command only stops the server started with the same database location. This local HTTP endpoint has no authentication; do not expose it to a network.

## Connect Claude Code via MCP

Run these commands on the same machine and in the same Python environment as Claude Code. Install the MCP extra and add a repository first.

**Windows Command Prompt or PowerShell**

```bat
python -m pip install -e ".[mcp]"
atomi-code-graph-search add "C:\dev\repo\my-project"
claude mcp add --scope user --transport stdio atomi-code-graph-search -- atomi-code-graph-search mcp stdio
claude mcp list
claude mcp get atomi-code-graph-search
```

**Linux or macOS**

```sh
python -m pip install -e '.[mcp]'
atomi-code-graph-search add /path/to/my-project
claude mcp add --scope user --transport stdio atomi-code-graph-search -- atomi-code-graph-search mcp stdio
claude mcp list
```

The dashboard also shows setup commands under **Connect Claude Code**, using the exact index path currently open in the browser. Start or restart Claude Code, run `/mcp`, then ask Claude to use `search_code`, `list_repositories`, or `source_graph`. The user scope makes it available in all your Claude Code projects. Claude starts its own stdio server, so `atomi-code-graph-search mcp start` is unnecessary for this setup; that command starts a separate localhost HTTP server. The dashboard (`web start`) is also independent. The default database is `~/.atomi-code-graph-search/index.sqlite3`. If you indexed with `--db`, register MCP with the same path using `atomi-code-graph-search --db "path-to-index.sqlite3" mcp stdio` after the `--` separator.

If `claude mcp list` shows a failed connection, check that `atomi-code-graph-search mcp stdio` starts in the terminal where `claude` runs and that both commands use the same Windows or WSL Python installation. A manual stdio run waits for its client without printing a prompt; press Ctrl+C to exit. MCP clients may transmit returned source snippets to their model provider.

## Source graphs

Open `http://127.0.0.1:8080/graph` from the dashboard. Select **File imports** or **Call sites** and a repository; click a node for connected edges. The graph is capped at 300 edges for browser performance. The CLI can export Graphviz DOT or JSON:

```sh
atomi-code-graph-search graph --repo my-repo --type imports --format dot > imports.dot
atomi-code-graph-search graph --repo my-repo --type calls --format json > calls.json
```

MCP also provides `source_graph`. Call sites are parsed with bundled Tree-sitter grammars for C/C++, Java, JavaScript, TypeScript, Bash, Rust, Go, Python and PHP. A direct call is linked to a definition only when the name occurs uniquely in the same file. Calls through objects, overloaded names, external functions, dynamic dispatch and shell commands without a local match remain visibly **unresolved**. Python also links some imported calls by name, labeled as such. This is a static, syntax-based graph: it does not prove the runtime target or trace calls across languages. HTML, Vue templates, configuration, and SQL do not have call graph extraction yet. File import edges resolve local Python imports, relative JavaScript/TypeScript/Vue imports, and explicit Java imports. Parsing requires the bundled `tree-sitter-language-pack==0.10.0` dependency; a reinstall and `atomi-code-graph-search refresh` builds graphs for existing repositories.

## Scope and limitations

Supported extensions include Python, Java, Kotlin, Go, Rust, C/C++, JavaScript, TypeScript, Vue, PHP, SQL, shell, common config and Markdown. Dependency/generated directories, symlinks, binary files and files larger than 1 MB are skipped. Source chunks are stored **in plain text** in the local SQLite database. Searches match any word and rank results using SQLite BM25. This does not prove coverage of all API endpoints or UI queries.

Run `python -m unittest discover -s tests` to test. The software is provided under the MIT license.
