"""The page: one self-contained HTML file, written where git does not look and no evidence rests.

The same file opens in a browser and publishes as an Artifact. The Artifact page contract forbids
a document wrapper of its own (doctype, html, head, body), so the page has none; it opens with a
charset declaration instead, which a browser honours in a local file and which is harmless inside
the wrapper an Artifact adds. Its data is one JSON document, ASCII-escaped, so no encoding guess
can garble it.

The directory carries its own `.gitignore`, so `git status` never lists the page whatever the
project ignores, and nothing the snapshot writes can be committed by a careless `git add -A`.
"""

from __future__ import annotations

import html
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

PAGE_DIR = ".graph-snapshot"
PAGE_FILE = "snapshot.html"
IGNORE_FILE = ".gitignore"
#: Every path a snapshot may write, relative to the project root.
PAGE_PATHS = (f"{PAGE_DIR}/{PAGE_FILE}", f"{PAGE_DIR}/{IGNORE_FILE}")


def template() -> str:
    return files("graph_snapshot").joinpath("page.html").read_text(encoding="utf-8")


def render(snap: dict[str, Any], focus: str | None = None) -> str:
    data = dict(snap, focus=focus or "")
    data.pop("page_named_by", None)
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    title = html.escape(snap["project"].replace("_", " ") + " graph snapshot")
    return template().replace("__TITLE__", title, 1).replace("__SNAPSHOT__", payload, 1)


def write(root: Path, snap: dict[str, Any], focus: str | None = None) -> str:
    """Write the page and say where, or say why nothing was written."""
    if snap.get("page_named_by"):
        return (f"page: not written -- {', '.join(snap['page_named_by'])} name{'s' if len(snap['page_named_by']) == 1 else ''} "
                f"{PAGE_DIR}/, so evidence rests on what is there and rewriting it would stale that "
                f"evidence. Drop {PAGE_DIR}/ from those declarations to take snapshots here.")
    directory = root / PAGE_DIR
    directory.mkdir(exist_ok=True)
    ignore = directory / IGNORE_FILE
    if not ignore.exists():
        ignore.write_text("# graph-snapshot output: regenerated on every snapshot, never committed\n*\n",
                          encoding="utf-8")
    page = directory / PAGE_FILE
    page.write_text(render(snap, focus), encoding="utf-8")
    return (f"page: {page} -- open it in a browser; to share it, publish that file as an Artifact "
            "when the person asks (it carries the design, so where it goes is theirs to say)")
