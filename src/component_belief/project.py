"""Which project the servers describe.

A server starts wherever its client launches it -- as a plugin, from the plugin's own install,
far from any project -- so the root is named rather than guessed: the server's own variable
first, then the project directory the client reports, and the working directory only when
neither is set. All three servers resolve it here, so they cannot disagree about which
repository's ledgers they are reading.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The project directory Claude Code reports, and expands in a plugin's MCP `env`.
CLIENT_PROJECT_DIR = "CLAUDE_PROJECT_DIR"


def project_root(*variables: str) -> Path:
    for var in (*variables, CLIENT_PROJECT_DIR):
        value = os.environ.get(var, "")
        # A client that does not expand `${...}` passes the placeholder through verbatim, and a
        # literal "${CLAUDE_PROJECT_DIR}" directory would be an empty project read in silence.
        if value and "${" not in value:
            return Path(value).resolve()
    return Path.cwd().resolve()
