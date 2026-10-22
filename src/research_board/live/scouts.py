"""What the research scouts are doing, read from Claude Code's transcripts of its subagents.

An adapter, not part of the board: it reads a client's own files, which are not a documented
interface, so everything here reads them defensively and decides nothing. The board shows a
scout's work once it records it; this shows the scout at work before that.

Claude Code keeps a project's sessions under ~/.claude/projects/<the project's path, each
character other than an ASCII letter or digit as "-">, and each subagent's transcript at
<session>/subagents/agent-<id>.jsonl, beside agent-<id>.meta.json naming its agent type. A scout
still running has no "finished" in that file, and many finished ones never get it, so a scout is
working while its transcript was written in the last few minutes, and the page says when it last
wrote.

Which direction a scout serves is read from its own calls -- the directions its trails, feedback
and new directions name, most first -- not from its brief, whose first id is often only the goal.
Each tool call is written twice (while streaming and complete), so calls are counted by id.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..board import direction_id

SCOUT_TYPE = "tdlp:research-scout"
RECENT = 180.0             # seconds since its last write within which a scout counts as working
KEEP = 12                  # scouts no longer working that are still listed
ACTIONS = 40               # latest actions listed per scout
_ID = re.compile(r"(?:DIR|GOL)-[A-Za-z0-9][A-Za-z0-9_.-]*")


def project_folder(root: Path, home: Path | None = None) -> Path:
    """Where Claude Code keeps the sessions started in `root`."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    return (home or Path.home()) / ".claude" / "projects" / slug


def _short(text: Any, n: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe(tool: str, given: dict[str, Any]) -> str:
    """One tool call as one plain line."""
    if tool == "WebSearch":
        return f"searched “{_short(given.get('query'), 140)}”"
    if tool == "WebFetch":
        return f"read {_short(str(given.get('url') or '').split('://', 1)[-1], 90)}"
    if tool == "board":
        where = given.get("direction") or given.get("goal") or given.get("section") or ""
        return f"read the board{' on ' + str(where) if where else ''}"
    if tool == "ledger":
        where = given.get("contract") or given.get("run") or given.get("node") or given.get("evidence") or ""
        return f"read the ledgers{' for ' + str(where) if where else ''}"
    if tool == "status":
        return f"read the {given.get('view', 'status')} view"
    if tool == "add_trail":
        return f"added a trail to {given.get('direction', '?')}: {_short(given.get('paper'), 140)}"
    if tool == "feedback":
        return f"{given.get('kind', 'note')} on {given.get('about', '?')}: {_short(given.get('text'), 160)}"
    if tool == "open_direction":
        return f"opened a direction “{given.get('name', '?')}” on {given.get('goal', '?')}: {_short(given.get('idea'), 140)}"
    return tool


class Transcript:
    """One scout's transcript, read incrementally: only the lines written since the last read."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.brief = ""
        self.said = ""
        self.first: str | None = None
        self.last: str | None = None
        self.calls: dict[str, None] = {}               # call ids seen, in order
        self.counts: Counter = Counter()
        self.directions: Counter = Counter()           # directions its own records name
        self.reading: str | None = None                # the last direction or goal it read the board on
        self.actions: list[dict[str, Any]] = []

    def read(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:                          # rewritten: read it again
            self.__init__(self.path)
        if size == self.offset:
            return
        with self.path.open("rb") as fh:
            fh.seek(self.offset)
            chunk = fh.read(size - self.offset)
        end = chunk.rfind(b"\n") + 1                    # a line still being written waits
        for line in chunk[:end].splitlines():
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(record, dict):
                self._take(record)
        self.offset += end

    def _take(self, record: dict[str, Any]) -> None:
        stamp = record.get("timestamp")
        if isinstance(stamp, str):
            self.first = self.first or stamp
            self.last = stamp
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        if message.get("role") == "user" and not self.brief:
            if isinstance(content, str):
                self.brief = content
            elif isinstance(content, list):
                self.brief = " ".join(str(b.get("text", "")) for b in content
                                      if isinstance(b, dict) and b.get("type") == "text")
        if message.get("role") != "assistant" or not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and str(block.get("text", "")).strip():
                self.said = str(block["text"]).strip()
            if block.get("type") != "tool_use":
                continue
            call = str(block.get("id") or "")
            if not call or call in self.calls:
                continue                                # each call is written twice
            self.calls[call] = None
            tool = str(block.get("name", "")).split("__")[-1]
            given = block.get("input") if isinstance(block.get("input"), dict) else {}
            self.counts[tool] += 1
            if tool in ("add_trail", "feedback") and _ID.fullmatch(str(given.get("direction") or "")):
                self.directions[str(given["direction"])] += 1
            elif tool == "feedback" and str(given.get("about") or "").startswith("DIR-"):
                self.directions[str(given["about"])] += 1
            elif tool == "open_direction" and given.get("name"):
                self.directions[direction_id(str(given["name"]))] += 1
            elif tool == "board" and (given.get("direction") or given.get("goal")):
                self.reading = str(given.get("direction") or given.get("goal"))
            self.actions.append({"at": stamp, "tool": tool, "what": describe(tool, given)})
            del self.actions[:-ACTIONS]


class ScoutWatch:
    """The scouts of one project, from the folders given."""

    def __init__(self, folders: list[Path], recent: float = RECENT, keep: int = KEEP) -> None:
        self.folders, self.recent, self.keep = folders, recent, keep
        self.transcripts: dict[Path, Transcript] = {}

    def poll(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        found = [f for f in self.folders if f.is_dir()]
        seen = []
        for folder in found:
            for meta_path in folder.glob("*/subagents/*.meta.json"):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not isinstance(meta, dict) or meta.get("agentType") != SCOUT_TYPE:
                    continue
                path = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + ".jsonl")
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                seen.append((mtime, path, meta))
        seen.sort(key=lambda s: s[0], reverse=True)
        scouts, quiet = [], 0
        for mtime, path, meta in seen:
            working = now - mtime < self.recent
            if not working:
                if quiet >= self.keep:
                    continue
                quiet += 1
            transcript = self.transcripts.setdefault(path, Transcript(path))
            transcript.read()
            brief_ids = _ID.findall(transcript.brief)
            goal = next((i for i in brief_ids if i.startswith("GOL-")), None)
            scouts.append({
                "id": path.stem, "description": str(meta.get("description") or path.stem),
                "working": working, "finished": meta.get("finished") is True,
                "last_write": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                "first": transcript.first, "last": transcript.last,
                "goal": goal, "directions": [[d, n] for d, n in transcript.directions.most_common()],
                "reading": transcript.reading, "brief_target": brief_ids[0] if brief_ids else None,
                "counts": {"searches": transcript.counts["WebSearch"], "pages": transcript.counts["WebFetch"],
                           "trails": transcript.counts["add_trail"], "feedback": transcript.counts["feedback"],
                           "directions": transcript.counts["open_direction"]},
                "actions": transcript.actions[::-1], "said": transcript.said[:1500],
            })
        if not found:
            empty = "no transcripts found in " + ", ".join(str(f) for f in self.folders)
        elif not seen:
            empty = "no scout has run in this project"
        else:
            empty = ""
        return {"enabled": True, "folders": [str(f) for f in self.folders], "empty": empty, "scouts": scouts}


OFF = {"enabled": False, "folders": [], "empty": "the scouts view is off (research-board serve --scouts claude-code)",
       "scouts": []}
