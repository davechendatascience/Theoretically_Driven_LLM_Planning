"""Write the verifier and the research scout for Codex and Antigravity from the Claude Code originals.

plugin/agents/*.md are the source. Claude Code narrows each agent to the tools its frontmatter
lists, so neither can open a file and each holds only its own few server tools. Codex and
Antigravity narrow less: a subagent there reaches every tdlp server the session has. So each
copy is the original prompt, word for word, behind a preamble that names the tools the original
holds and asks for those only, and frontmatter that takes away what the client can take away:

  Antigravity  a Markdown agent whose `tools:` lists no file or command tool (checked: a subagent
               declared so cannot read a workspace file), with the session's MCP servers shared
               through `inheritMcp`, so the verifier writes to the same server process as the
               agent that sent it.
  Codex        a TOML agent with the shell and command tools switched off. MCP servers cannot be
               narrowed per agent in Codex; they come from the session.

Usage:
    python tools/client_agents.py          # rewrite clients/*/agents/
    python tools/client_agents.py --check  # exit 1, naming each file that is out of date
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "plugin" / "agents"
CLIENTS = REPO / "clients"
PLUGIN = "tdlp"

#: How each client names the two Claude Code tools a scout uses that are not a server's.
WEB = {"codex": "your web search", "antigravity": "search_web and read_url_content"}
#: What each Antigravity agent holds besides the session's MCP servers: nothing that opens a file.
ANTIGRAVITY_TOOLS = {"consistency-verifier": [], "research-scout": ["search_web", "read_url_content"]}
#: Codex tools that would let an agent read the project; the verifier and the scout hold none.
CODEX_OFF = ["shell_tool", "unified_exec", "apps", "plugins", "browser_use", "computer_use"]


def split(path: Path) -> tuple[dict, str]:
    """The frontmatter and the body of a Claude Code agent file."""
    _, front, body = path.read_text(encoding="utf-8").split("---\n", 2)
    return yaml.safe_load(front), body.lstrip("\n")


def held(front: dict) -> dict[str, list[str]]:
    """The server tools the Claude Code agent holds, by server, and the other tools it holds."""
    out: dict[str, list[str]] = {}
    for name in (t.strip() for t in str(front["tools"]).split(",")):
        if name.startswith(f"mcp__plugin_{PLUGIN}_"):
            server, _, tool = name.removeprefix(f"mcp__plugin_{PLUGIN}_").partition("__")
            out.setdefault(server, []).append(tool)
        else:
            out.setdefault("", []).append(name)
    return out


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def preamble(name: str, front: dict, client: str) -> str:
    tools = held(front)
    parts = [f"{server}'s {_and(names)}" for server, names in tools.items() if server]
    if tools.get(""):
        parts.append(f"{WEB[client]} where this text says {_and(tools[''])}")
    uses = "; ".join(parts[:-1]) + "; and " + parts[-1] if len(parts) > 1 else parts[0]
    title = {"codex": "Codex", "antigravity": "Antigravity"}[client]
    return (f"On {title} you can reach every tdlp server's tools, not only your own. Use {uses} "
            f"-- the tools {name} holds on Claude Code -- and no other. Do not open a file or "
            "run a command by any tool you hold. Each other tool would show you what this protocol "
            "keeps from you, or make a move that is not yours.\n\n")


def antigravity(name: str, front: dict, body: str) -> str:
    lines = ["---", f"name: {name}", f"description: {json.dumps(front['description'])}",
             f"tools: [{', '.join(ANTIGRAVITY_TOOLS[name])}]", "inheritMcp: true", "---",
             f"# {name}", ""]
    return "\n".join(lines) + "\n" + preamble(name, front, "antigravity") + body


def codex(name: str, front: dict, body: str) -> str:
    text = preamble(name, front, "codex") + body
    assert "'''" not in text, f"{name}: the prompt cannot sit in a TOML literal string"
    lines = [f"name = {json.dumps(name)}", f"description = {json.dumps(front['description'])}",
             f"developer_instructions = '''\n{text}'''", "", "[features]"]
    lines += [f"{feature} = false" for feature in CODEX_OFF]
    return "\n".join(lines) + "\n"


def rendered() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for path in sorted(SOURCE.glob("*.md")):
        front, body = split(path)
        name = front["name"]
        out[CLIENTS / "antigravity" / "agents" / f"{name}.md"] = antigravity(name, front, body)
        out[CLIENTS / "codex" / "agents" / f"{name}.toml"] = codex(name, front, body)
    return out


def main(argv: list[str]) -> int:
    files = rendered()
    if "--check" in argv:
        stale = [p for p, text in files.items()
                 if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for path in stale:
            print(f"out of date: {path.relative_to(REPO)} -- run: python tools/client_agents.py",
                  file=sys.stderr)
        return 1 if stale else 0
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
