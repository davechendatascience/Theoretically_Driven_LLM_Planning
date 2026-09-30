"""The plugin: what any project loads, at a pinned version, pointed at that project.

Each mistake here fails silently in someone else's repository. A server that reads the wrong
root reports an empty ledger as though nothing had been measured. A tag that is not this version
runs other code than the one reviewed. A verifier that names a tool its server does not register
starts with no tools at all. So they are checked here, where they can fail loudly.
"""

from __future__ import annotations

import asyncio
import json
import re
import tomllib
from pathlib import Path

from component_belief.goals import RELEASES
from component_belief.project import project_root

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
ROOT_VARS = ("BELIEF_PROJECT_ROOT", "CONSISTENCY_PROJECT_ROOT", "STAMP_MONITOR_ROOT")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


MANIFEST = _json(PLUGIN / ".claude-plugin" / "plugin.json")
SERVERS = _json(PLUGIN / ".mcp.json")["mcpServers"]
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


class TestProjectRoot:
    def test_the_servers_own_variable_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(tmp_path / "named"))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "client"))
        assert project_root("BELIEF_PROJECT_ROOT") == (tmp_path / "named").resolve()

    def test_the_project_claude_code_reports_is_next(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BELIEF_PROJECT_ROOT", raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert project_root("BELIEF_PROJECT_ROOT") == tmp_path.resolve()

    def test_an_unexpanded_placeholder_names_no_directory(self, tmp_path, monkeypatch):
        """A client that does not expand ${...} passes it through; reading a directory literally
        named that would report an empty project in silence."""
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", "${CLAUDE_PROJECT_DIR}")
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        assert project_root("BELIEF_PROJECT_ROOT") == tmp_path.resolve()

    def test_all_three_servers_resolve_the_same_project(self, tmp_path, monkeypatch):
        from component_belief import server as component
        from consistency_belief import server as consistency
        from stamp_monitor import server as monitor

        for var in ROOT_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        roots = {component.project_root(), consistency.project_root(), monitor.project_root()}
        assert roots == {tmp_path.resolve()}


class TestManifest:
    def test_one_version_everywhere(self):
        market = _json(REPO / ".claude-plugin" / "marketplace.json")
        [entry] = [p for p in market["plugins"] if p["name"] == MANIFEST["name"]]
        assert entry["source"] == "./plugin"
        from component_belief import __version__

        assert MANIFEST["version"] == entry["version"] == PYPROJECT["project"]["version"] == __version__

    def test_every_server_installs_from_this_versions_tag(self):
        """`claude plugin tag` names a release <name>--v<version>; the servers install from that
        tag, so the code a project runs is the code this version shipped."""
        tag = f"{MANIFEST['name']}--v{MANIFEST['version']}"
        scripts = PYPROJECT["project"]["scripts"]
        assert set(SERVERS) == {"component-belief", "consistency-belief", "stamp-monitor"}
        for name, server in SERVERS.items():
            args = server["args"]
            source = args[args.index("--from") + 1]
            assert source == f"{RELEASES}@{tag}", f"{name} installs from {source}, not {tag}"
            assert args[-1] in scripts, f"{name} runs {args[-1]}, which pyproject does not install"

    def test_every_server_reads_the_project_claude_code_reports(self):
        for name, server in SERVERS.items():
            roots = [value for key, value in server["env"].items() if key in ROOT_VARS]
            assert roots == ["${CLAUDE_PROJECT_DIR}"], name

    def test_every_server_installs_by_copying(self):
        """uv hardlinks cached files into the environments it builds; under a synced folder
        (OneDrive) a hardlinked file can be refused a cloud operation, failing the install, or
        emptied later. Copying costs disk and removes both."""
        for name, server in SERVERS.items():
            assert server["env"].get("UV_LINK_MODE") == "copy", name

    def test_the_verifier_holds_only_tools_its_server_registers(self):
        """No Read, Grep or Bash: every tool is a consistency-belief tool, under the name a
        plugin server's tools carry, and each is one the server registers."""
        from consistency_belief import server as consistency

        text = (PLUGIN / "agents" / "consistency-verifier.md").read_text(encoding="utf-8")
        names = [t.strip() for t in re.search(r"^tools:(.*)$", text, re.M).group(1).split(",")]
        prefix = f"mcp__plugin_{MANIFEST['name']}_consistency-belief__"
        assert names and all(n.startswith(prefix) for n in names), names
        registered = {t.name for t in asyncio.run(consistency.mcp.list_tools())}
        assert {n.removeprefix(prefix) for n in names} <= registered

    def test_every_skill_is_where_the_plugin_loads_it(self):
        skills = sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md"))
        assert skills == ["component-belief", "consistency-belief"]
        for name in skills:
            front = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
            assert f"name: {name}" in front
