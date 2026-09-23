"""Integration test over the real MCP stdio transport.

Every other test in this suite calls the server's Python functions directly.
That is faster and it is where the logic lives — but it cannot catch a whole
class of bug, and one of them shipped: children spawned by the server inherit
its stdin, which over MCP is the JSON-RPC pipe the client holds open. Any child
touching stdin blocks until the timeout.

The symptom was silent and total. `git show` timed out, `load()` fell through
to "no declarations at HEAD", and the server answered every query with an empty
graph while reporting no error. `run_test` was equally dead: every declared
command hung.

So this file drives the server the way a client does. It is slow, and that is
the price of testing the thing that actually runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

TIMEOUT_S = 60


class Client:
    """A minimal JSON-RPC client over the server's stdio."""

    def __init__(self, cwd: Path, env_extra: dict[str, str] | None = None):
        import os
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        env.update(env_extra or {})
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "component_belief.server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=env, cwd=str(cwd),
        )
        self._id = 0
        self._send({"jsonrpc": "2.0", "id": self._next(), "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "test", "version": "1"}}})
        self._await(1)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _next(self) -> int:
        self._id += 1
        return self._id

    def _send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _await(self, msg_id: int) -> dict:
        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise AssertionError("server closed the stream")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == msg_id:
                return msg
        raise AssertionError(f"no response to id={msg_id} within {TIMEOUT_S}s")

    def call(self, tool: str, **arguments) -> str:
        msg_id = self._next()
        self._send({"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments}})
        result = self._await(msg_id)["result"]
        return "".join(part.get("text", "") for part in result.get("content", []))

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=10)


@pytest.fixture
def client(repo):
    c = Client(repo)
    yield c
    c.close()


def test_declarations_load_over_stdio(client):
    """The regression. A child inheriting the MCP stdin pipe hangs, git times
    out, and the server silently reports an empty graph."""
    out = client.call("status", view="graph")
    assert "NONE IN EFFECT" not in out, \
        "declarations failed to load over stdio — check child stdin inheritance"
    assert "git HEAD" in out
    assert "CMP-grasp" in out


def test_declarations_load_quickly_over_stdio(client):
    """Speed is the tell. The broken version 'worked' after a 15s git timeout,
    so a correctness-only assertion would pass on a server that is dead."""
    start = time.time()
    client.call("status", view="graph")
    elapsed = time.time() - start
    assert elapsed < 10, f"status took {elapsed:.1f}s; a child is blocking on stdin"


def test_run_test_executes_over_stdio(repo):
    """run_test shells out too, so it died the same way — every declared
    command hung until its timeout."""
    script = repo / "emit.py"
    script.write_text(
        "import json, os\n"
        "json.dump({'trials': [{'metrics': {'ik_success': True}}]}, open(os.environ['OUT'], 'w'))\n",
        encoding="utf-8",
    )
    from conftest import git
    yaml = (repo / "belief.yaml").read_text(encoding="utf-8").replace(
        'run: "echo ok"', f'run: python "{script}"')
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "runnable")

    c = Client(repo)
    try:
        out = c.call("run_test", test_id="TST-grasp-ik")
        assert "trials=1" in out, out
        assert "records=1" in out, out
        belief = c.call("status", view="belief")
        assert "CTR-grasp-reachable" in belief
    finally:
        c.close()


def test_note_is_inert_over_stdio(client):
    out = client.call("note", subject="CMP-grasp", text="bench observation")
    assert "not belief-eligible" in out


def test_six_tools_over_stdio(client):
    msg_id = client._next()
    client._send({"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": {}})
    tools = client._await(msg_id)["result"]["tools"]
    assert sorted(t["name"] for t in tools) == [
        "amend", "decide", "ingest", "note", "run_test", "status",
    ]
