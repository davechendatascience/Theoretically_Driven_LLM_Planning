"""GOL-cross-coding-agents: Claude Code, Codex and Antigravity can each run the harness on my project.
Whichever agent I use, the servers read the project the agent is working in and run its tests in
that project's environment, the agent's commits to my goal set are refused, and the agent can send
the verifier and the research scout, neither holding a tool that opens a file or runs a command.

Each agent starts the servers its own way, and that is what is reproduced here:
  Claude Code  expands ${CLAUDE_PROJECT_DIR} in the plugin's config (test_any_project.py).
  Codex        expands nothing and names no workspace, and starts each server in the directory
               Codex was started in.
  Antigravity  expands nothing and starts a plugin's server in the plugin's own folder, and names
               the open workspace when the server asks (MCP roots/list).
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

import anyio
import pytest
import yaml
from component_belief.goals import install
from component_belief.runner import project_environment
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from conftest import SRC, commit, git

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
CLIENTS = REPO / "clients"
NAMED_ROOTS = ("BELIEF_PROJECT_ROOT", "CONSISTENCY_PROJECT_ROOT", "STAMP_MONITOR_ROOT", "GRAPH_SNAPSHOT_ROOT",
               "RESEARCH_BOARD_ROOT", "CLAUDE_PROJECT_DIR")
#: What opens a file or runs a command, by the name each agent gives it.
FILE_TOOLS = {"Read", "Grep", "Glob", "Bash", "Edit", "Write", "NotebookEdit",
              "view_file", "read_file", "list_dir", "grep_search", "find_by_name", "run_command"}


def _servers():
    from component_belief import server as component
    from consistency_belief import server as consistency
    from graph_snapshot import server as snapshot
    from research_board import server as research
    from stamp_monitor import server as monitor

    return [(component, "status", {"view": "graph"}), (consistency, "status", {"view": "tree"}),
            (monitor, "workflow", {}), (snapshot, "snapshot", {}), (research, "board", {})]


@pytest.fixture
def nothing_named(project: Path, monkeypatch) -> Path:
    """The project, with no variable naming it to a server: Codex and Antigravity expand none."""
    for var in NAMED_ROOTS:
        monkeypatch.delenv(var, raising=False)
    return project


def test_on_codex_every_server_reads_the_project_codex_was_started_in(nothing_named, monkeypatch):
    monkeypatch.chdir(nothing_named)
    assert {module.project_root() for module, _, _ in _servers()} == {nothing_named.resolve()}


def test_on_antigravity_every_server_reads_the_workspace_antigravity_names(nothing_named, tmp_path_factory,
                                                                           monkeypatch):
    from component_belief import project as roots

    plugin = tmp_path_factory.mktemp("plugins")
    monkeypatch.chdir(plugin)
    monkeypatch.setenv("PLUGIN_ROOT", str(plugin))

    async def workspace(_context) -> types.ListRootsResult:
        return types.ListRootsResult(roots=[types.Root(uri=nothing_named.as_uri())])

    async def ask(module, tool: str, arguments: dict) -> str:
        async with create_connected_server_and_client_session(module.mcp, list_roots_callback=workspace) as client:
            result = await client.call_tool(tool, arguments)
        return "".join(getattr(part, "text", "") for part in result.content)

    for module, tool, arguments in _servers():
        monkeypatch.setattr(roots, "_client_roots", [])
        out = anyio.run(ask, module, tool, arguments)
        assert "no project" not in out, (module.__name__, out)
        assert module.project_root() == nothing_named.resolve(), module.__name__
        if tool == "status" and arguments["view"] == "graph":
            assert "CMP-planner" in out


@pytest.mark.parametrize("launch", [{"CLAUDE_PLUGIN_ROOT": "plugin"}, {"PLUGIN_ROOT": "plugin"},
                                    {"TDLP_ISOLATED": "1"}], ids=["claude-code", "antigravity-plugin", "uvx"])
def test_on_any_agent_a_project_test_runs_with_the_projects_python(project, tmp_path_factory, monkeypatch, launch):
    tool = tmp_path_factory.mktemp("uv-cache") / ("Scripts" if os.name == "nt" else "bin")
    monkeypatch.setattr("sys.executable", str(tool / "python"))
    project_bin = project / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    project_bin.mkdir(parents=True)
    env = project_environment(project, {"PATH": os.pathsep.join([str(tool), "/usr/bin"]), **launch})
    entries = env["PATH"].split(os.pathsep)
    assert entries[0] == str(project_bin) and str(tool) not in entries


GOALS_YAML = """
goals:
  - {id: GOL-plans, outcome: Planned grasps succeed on the bench, measure: CTR-plans-succeed}
contracts:
  - {id: CTR-plans-succeed, subject: GOL-plans, kind: gate, metrics: [{id: passed, unit: bool}],
     acceptance: {rule: "passed == true"}, evaluable_by: [TST-bench]}
tests:
  - {id: TST-bench, layer: e2e, targets: [GOL-plans], run: python bench.py $OUT, metrics: [passed]}
"""
BENCH_PY = "import json, sys\njson.dump([{'metrics': {'passed': True}}], open(sys.argv[1], 'w'))\n"


@pytest.mark.parametrize("agent, trailer, env", [
    ("claude-code", "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", {}),
    ("codex", "\n\nCo-authored-by: Codex <noreply@openai.com>", {}),
    ("antigravity", "", {"ANTIGRAVITY_AGENT": "1"}),
])
def test_whichever_agent_commits_to_my_goal_set_it_is_refused(project, monkeypatch, agent, trailer, env):
    (project / "goals.yaml").write_text(GOALS_YAML, encoding="utf-8")
    (project / "bench.py").write_text(BENCH_PY, encoding="utf-8")
    commit(project, "my goals")
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    install(project, command=f'"{Path(sys.executable).as_posix()}" -m component_belief.goals check')

    (project / "bench.py").write_text(BENCH_PY + "# always pass\n", encoding="utf-8")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    refused = git(project, "commit", "-qam", "loosen the bench" + trailer)
    assert refused.returncode != 0 and "bench.py" in refused.stderr, agent
    for name in env:
        monkeypatch.delenv(name)
    assert git(project, "commit", "-qam", "I loosened the bench myself").returncode == 0


def _claude_agent(name: str) -> tuple[set[str], str]:
    _, front, body = (PLUGIN / "agents" / f"{name}.md").read_text(encoding="utf-8").split("---\n", 2)
    tools = {t.strip() for t in str(yaml.safe_load(front)["tools"]).split(",")}
    return tools, body.strip()


@pytest.mark.parametrize("name", ["consistency-verifier", "research-scout"])
def test_every_agent_can_send_it_and_it_cannot_open_a_file(name):
    tools, prompt = _claude_agent(name)
    assert tools and not tools & FILE_TOOLS, ("claude-code", tools)

    text = (CLIENTS / "antigravity" / "agents" / f"{name}.md").read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["name"] == name and not set(front["tools"]) & FILE_TOOLS, ("antigravity", front["tools"])
    assert set(front["tools"]) <= {"search_web", "read_url_content"}, ("antigravity", front["tools"])
    assert prompt in text, "antigravity: not the same instructions"

    agent = tomllib.loads((CLIENTS / "codex" / "agents" / f"{name}.toml").read_text(encoding="utf-8"))
    assert agent["name"] == name and prompt in agent["developer_instructions"], "codex: not the same instructions"
    assert agent["features"]["shell_tool"] is False and agent["features"]["unified_exec"] is False, "codex"


def test_every_agent_installs_the_release_the_plugin_names():
    plugin = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    codex = tomllib.loads((CLIENTS / "codex" / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
    antigravity = json.loads((CLIENTS / "antigravity" / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]
    for client, servers in (("codex", codex), ("antigravity", antigravity)):
        assert {name: s["args"] for name, s in servers.items()} == {name: s["args"] for name, s in plugin.items()}, client
