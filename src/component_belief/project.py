"""Which project the servers describe.

A server starts wherever its client launches it -- as a plugin, from the plugin's own install,
far from any project -- so the root is named rather than guessed: the server's own variable
first, then the project directory the client reports, then the workspace the client names over
MCP (its roots), and the working directory only when none of those is given. All five servers
resolve it here, so they cannot disagree about which repository's ledgers they are reading.

Clients differ in which of these they give. Claude Code expands ${CLAUDE_PROJECT_DIR} in a
plugin's config. Codex expands nothing and names no roots, but starts a server in the directory
it was started in. Antigravity expands nothing either and starts a plugin's server in the
plugin's own folder, but answers roots/list with the open workspace. A working directory inside
the plugin's install is never a project, so it is refused rather than read as an empty one.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import anyio
from mcp import types
from mcp.server.fastmcp import FastMCP

#: The project directory Claude Code reports, and expands in a plugin's MCP `env`.
CLIENT_PROJECT_DIR = "CLAUDE_PROJECT_DIR"
#: Where a client installed the plugin it starts a server from: Claude Code's name for it, then
#: the Agent Plugins name (Antigravity, Codex). A server started there is not in any project.
PLUGIN_DIRS = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")
#: How long a client has to answer roots/list before the server goes on without its answer.
ROOTS_TIMEOUT_S = 5.0

#: The workspace directories the client named over MCP, in its order; empty until it names any.
_client_roots: list[Path] = []


class NoProject(RuntimeError):
    """The server was started in its plugin's install and nothing names the project."""


def _named(value: str) -> bool:
    # A client that does not expand `${...}` passes the placeholder through verbatim, and a
    # literal "${CLAUDE_PROJECT_DIR}" directory would be an empty project read in silence.
    return bool(value) and "${" not in value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def project_root(*variables: str) -> Path:
    for var in (*variables, CLIENT_PROJECT_DIR):
        value = os.environ.get(var, "")
        if _named(value):
            return Path(value).resolve()
    if _client_roots:
        return _client_roots[0]
    cwd = Path.cwd().resolve()
    for var in PLUGIN_DIRS:
        plugin = os.environ.get(var, "")
        if _named(plugin) and _inside(cwd, Path(plugin)):
            names = ", ".join(variables or ("BELIEF_PROJECT_ROOT",))
            raise NoProject(
                f"no project: this server was started in its plugin's install ({cwd}) and its client "
                f"named no workspace. Set {names} to the project's directory in the server's MCP "
                f"config, or start the client from the project.")
    return cwd


def set_client_roots(uris: list[str]) -> None:
    """Record the workspace the client names: each file:// root that is a directory, in order."""
    roots = []
    for uri in uris:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            continue
        path = Path(url2pathname(unquote(parsed.path)))
        if path.is_dir():
            roots.append(path.resolve())
    _client_roots[:] = roots


class ProjectServer(FastMCP):
    """A FastMCP server that asks its client which workspace it has open.

    Before a client's first tool call, and again after it says its roots changed, the server asks
    roots/list of a client that declared roots, so a client that names no project directory any
    other way (Antigravity) still points the server at the open workspace. A client that declares
    no roots is never asked and inherits none from an earlier client; one that does not answer in
    time leaves the roots as they were.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._roots_session: Any = None
        self._roots_current = False
        self._mcp_server.notification_handlers[types.RootsListChangedNotification] = self._roots_changed

    async def _roots_changed(self, _notification: Any) -> None:
        self._roots_current = False

    async def _learn_roots(self) -> None:
        try:
            session = self.get_context().session
        except ValueError:     # no request in flight: nobody to ask
            return
        if session is self._roots_session and self._roots_current:
            return
        if session is not self._roots_session:
            set_client_roots([])
        self._roots_session, self._roots_current = session, True
        try:
            params = session.client_params
            if params is None or params.capabilities.roots is None:
                return
            with anyio.fail_after(ROOTS_TIMEOUT_S):
                result = await session.list_roots()
        except Exception:      # a client that cannot answer leaves the other routes to the project
            return
        set_client_roots([str(root.uri) for root in result.roots])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self._learn_roots()
        return await super().call_tool(name, arguments)
