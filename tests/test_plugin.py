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
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from component_belief.goals import RELEASES
from component_belief.project import NoProject, project_root, set_client_roots

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
ROOT_VARS = ("BELIEF_PROJECT_ROOT", "CONSISTENCY_PROJECT_ROOT", "STAMP_MONITOR_ROOT", "GRAPH_SNAPSHOT_ROOT",
             "RESEARCH_BOARD_ROOT")


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

    def test_the_workspace_the_client_names_is_next(self, tmp_path, monkeypatch):
        """Antigravity expands no variable and starts a plugin's server in the plugin's own folder,
        but answers roots/list with the open workspace."""
        monkeypatch.delenv("BELIEF_PROJECT_ROOT", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        workspace = tmp_path / "my project"
        workspace.mkdir()
        set_client_roots(["https://example.com/not-a-directory", workspace.as_uri()])
        assert project_root("BELIEF_PROJECT_ROOT") == workspace.resolve()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert project_root("BELIEF_PROJECT_ROOT") == tmp_path.resolve(), "a named directory comes first"

    def test_where_the_client_starts_the_server_is_last(self, tmp_path, monkeypatch):
        """Codex expands nothing and names no roots, but starts the server where it was started."""
        monkeypatch.delenv("BELIEF_PROJECT_ROOT", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        assert project_root("BELIEF_PROJECT_ROOT") == tmp_path.resolve()

    @pytest.mark.parametrize("var", ["CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT"])
    def test_the_plugins_own_folder_is_no_project(self, tmp_path, monkeypatch, var):
        """Started in its install with nothing naming the project, a server says so; read as a
        project, the plugin's folder would report an empty ledger as though nothing was measured."""
        monkeypatch.delenv("BELIEF_PROJECT_ROOT", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        plugin = tmp_path / "plugins" / "tdlp"
        plugin.mkdir(parents=True)
        monkeypatch.setenv(var, str(plugin))
        monkeypatch.chdir(plugin)
        with pytest.raises(NoProject, match="BELIEF_PROJECT_ROOT"):
            project_root("BELIEF_PROJECT_ROOT")
        set_client_roots([tmp_path.as_uri()])
        assert project_root("BELIEF_PROJECT_ROOT") == tmp_path.resolve()

    def test_every_server_resolves_the_same_project(self, tmp_path, monkeypatch):
        from component_belief import server as component
        from consistency_belief import server as consistency
        from graph_snapshot import server as snapshot
        from research_board import server as research
        from stamp_monitor import server as monitor

        for var in ROOT_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        roots = {component.project_root(), consistency.project_root(), monitor.project_root(),
                 snapshot.project_root(), research.project_root()}
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
        assert set(SERVERS) == {"component-belief", "consistency-belief", "stamp-monitor", "graph-snapshot",
                                "research-board"}
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

    def test_the_scout_holds_no_code_tool_and_no_director_tool(self):
        """A scout reads the board, the ledgers and the web, never the code: no Read, Grep, Glob or
        Bash, and none of the director's moves (approve, spend, reflect). Every server tool it
        names is one its server registers, under the plugin's name for it."""
        from component_belief import server as component
        from consistency_belief import server as consistency
        from research_board import server as research

        text = (PLUGIN / "agents" / "research-scout.md").read_text(encoding="utf-8")
        names = [t.strip() for t in re.search(r"^tools:(.*)$", text, re.M).group(1).split(",")]
        assert not {"Read", "Grep", "Glob", "Bash", "Edit", "Write", "NotebookEdit"} & set(names), names
        servers = {"research-board": research, "component-belief": component, "consistency-belief": consistency}
        held = {}
        for name in names:
            if name in ("WebSearch", "WebFetch"):
                continue
            server, _, tool = name.removeprefix(f"mcp__plugin_{MANIFEST['name']}_").partition("__")
            assert server in servers, name
            held.setdefault(server, set()).add(tool)
        for server, tools in held.items():
            registered = {t.name for t in asyncio.run(servers[server].mcp.list_tools())}
            assert tools <= registered, (server, tools - registered)
        assert held["research-board"] == {"board", "ledger", "open_direction", "add_trail", "feedback"}
        assert held.get("component-belief", set()) <= {"status"} and held.get("consistency-belief", set()) <= {"status"}

    def test_every_skill_is_where_the_plugin_loads_it(self):
        skills = sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md"))
        assert skills == ["adopt-goals", "component-belief", "consistency-belief", "research"]
        for name in skills:
            front = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
            assert f"name: {name}" in front


CLIENTS = REPO / "clients"
CODEX = tomllib.loads((CLIENTS / "codex" / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
ANTIGRAVITY = _json(CLIENTS / "antigravity" / "mcp_config.json")["mcpServers"]


class TestOtherClients:
    """Codex and Antigravity load the same servers from their own MCP configs, and the verifier and
    the scout from their own agent files. The configs are copied into a user's setup by hand, so a
    drift from the plugin's would fail in someone else's repository, quietly."""

    @pytest.mark.parametrize("client", ["codex", "antigravity"])
    def test_each_client_starts_the_plugins_servers_from_this_versions_tag(self, client):
        servers = {"codex": CODEX, "antigravity": ANTIGRAVITY}[client]
        assert set(servers) == set(SERVERS)
        for name, server in servers.items():
            assert server["command"] == SERVERS[name]["command"] == "uvx"
            assert server["args"] == SERVERS[name]["args"], (client, name)

    @pytest.mark.parametrize("client", ["codex", "antigravity"])
    def test_each_client_names_no_project_and_marks_the_tool_environment(self, client):
        """Neither client expands a variable, so a root variable could only name one fixed
        directory; the project comes from where Codex starts the server, or from the workspace
        Antigravity names. TDLP_ISOLATED tells the runner the server's python is not the project's."""
        servers = {"codex": CODEX, "antigravity": ANTIGRAVITY}[client]
        for name, server in servers.items():
            env = server["env"]
            assert not set(env) & set(ROOT_VARS), (client, name)
            assert env["TDLP_ISOLATED"] == "1" and env["UV_LINK_MODE"] == "copy", (client, name)
            plugin_env = {k: v for k, v in SERVERS[name]["env"].items() if k not in ROOT_VARS}
            assert {k: v for k, v in env.items() if k != "TDLP_ISOLATED"} == plugin_env, (client, name)

    def test_codex_waits_for_the_first_build(self):
        """Codex gives a server 10 s to start by default; the first start at a release takes longer."""
        for name, server in CODEX.items():
            assert server["startup_timeout_sec"] >= 120, name

    def test_the_client_agents_are_written_from_the_claude_code_ones(self):
        sys.path.insert(0, str(REPO / "tools"))
        try:
            import client_agents
        finally:
            sys.path.pop(0)
        files = client_agents.rendered()
        assert {p.relative_to(CLIENTS).as_posix() for p in files} == {
            f"{c}/agents/{n}.{ext}" for c, ext in (("codex", "toml"), ("antigravity", "md"))
            for n in ("consistency-verifier", "research-scout")}
        for path, text in files.items():
            assert path.read_text(encoding="utf-8") == text, f"{path} -- run: python tools/client_agents.py"
            body = (PLUGIN / "agents" / f"{path.stem}.md").read_text(encoding="utf-8").split("---\n", 2)[2]
            assert body.lstrip("\n") in text, f"{path} is not the Claude Code prompt"

    def test_on_antigravity_neither_agent_holds_a_file_tool(self):
        for name, allowed in (("consistency-verifier", set()), ("research-scout", {"search_web", "read_url_content"})):
            front = yaml.safe_load((CLIENTS / "antigravity" / "agents" / f"{name}.md")
                                   .read_text(encoding="utf-8").split("---\n")[1])
            assert front["name"] == name and set(front["tools"]) == allowed
            assert front["inheritMcp"] is True, "the session's servers, not a second process on the ledger"

    def test_on_codex_neither_agent_holds_the_shell(self):
        for name in ("consistency-verifier", "research-scout"):
            agent = tomllib.loads((CLIENTS / "codex" / "agents" / f"{name}.toml").read_text(encoding="utf-8"))
            assert agent["name"] == name and agent["developer_instructions"].strip()
            assert agent["features"]["shell_tool"] is False and agent["features"]["unified_exec"] is False


def test_this_project_gives_the_servers_time_to_build_after_an_update():
    """The first start at a new tag clones, builds and installs (50-100 s measured), against a 30 s
    default connect limit; every server then fails with CONNECT_TIMEOUT for the session. A plugin
    cannot raise that limit, so the project that enables it does, beside enabledPlugins."""
    settings = _json(REPO / ".claude" / "settings.json")
    assert int(settings["env"]["MCP_TIMEOUT"]) >= 120_000
