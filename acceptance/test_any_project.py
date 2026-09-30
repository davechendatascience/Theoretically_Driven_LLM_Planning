"""GOL-any-project: the harness runs in any project at a pinned version, reading that project and
running its tests in that project's environment."""

from __future__ import annotations

import json
import os
from pathlib import Path

from component_belief.runner import project_environment

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
ROOT_VARS = ("BELIEF_PROJECT_ROOT", "CONSISTENCY_PROJECT_ROOT", "STAMP_MONITOR_ROOT")


def test_all_three_servers_read_the_project_claude_code_reports(tmp_path, monkeypatch):
    from component_belief import server as component
    from consistency_belief import server as consistency
    from stamp_monitor import server as monitor

    for var in ROOT_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert {component.project_root(), consistency.project_root(), monitor.project_root()} \
        == {tmp_path.resolve()}


def test_the_plugin_installs_the_release_of_its_own_version():
    version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    servers = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"component-belief", "consistency-belief", "stamp-monitor"}
    for server in servers.values():
        source = server["args"][server["args"].index("--from") + 1]
        assert source.endswith(f"@tdlp--v{version}")


def test_as_a_plugin_a_project_test_runs_with_the_projects_python(project, tmp_path_factory, monkeypatch):
    tool = tmp_path_factory.mktemp("uv-cache") / ("Scripts" if os.name == "nt" else "bin")
    monkeypatch.setattr("sys.executable", str(tool / "python"))
    project_bin = project / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    project_bin.mkdir(parents=True)
    env = project_environment(project, {"PATH": os.pathsep.join([str(tool), "/usr/bin"]),
                                        "CLAUDE_PLUGIN_ROOT": "plugin"})
    entries = env["PATH"].split(os.pathsep)
    assert entries[0] == str(project_bin) and str(tool) not in entries
