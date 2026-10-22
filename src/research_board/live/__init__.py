"""The research board for a person to watch: the live view (server.py) and its export (DEF-live-board).

One page serves both. The live view wraps it in a document of its own, inlines the latest board and
connects it to the server's event stream; it loads nothing from another host. The export inlines
one board and writes the page as a fragment a Claude Artifact can publish -- no document wrapper,
fonts from Google Fonts and Mermaid from jsDelivr, pinned by its integrity hash, which is all an
Artifact's frame lets a page load. The export is published only when the person asks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PAGE = HERE / "page.html"
MERMAID = HERE / "mermaid.min.js"
MERMAID_VERSION = "10.9.8"
MERMAID_SRI = "sha384-N3QqR/7q+xm3BGX+CBbNI8AUmRRqcsDzToy+0z1NLDI0QmTKW8zvwLvqulJgk3dP"
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500'
         '&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;'
         '1,6..72,400&display=swap">')

EXPORT_DIR = ".research-board"
EXPORT_FILES = ("board.html", "board.json", ".gitignore")


def _inline(data: Any) -> str:
    """JSON for a <script type="application/json"> element: nothing in it can close the element."""
    return json.dumps(data, default=str).replace("</", "<\\/").replace("<!--", "<\\!--")


def render(data: dict[str, Any], scouts: dict[str, Any] | None, *, nonce: str = "") -> str:
    """The page with `data` inlined. A live board (data["meta"]["mode"] == "live") gets a whole
    document whose scripts carry `nonce`; a snapshot gets the fragment an Artifact publishes."""
    live = data["meta"]["mode"] == "live"
    page = PAGE.read_text(encoding="utf-8")
    initial = (f'<script id="initial" type="application/json">{_inline(data)}</script>'
               f'<script id="initial-scouts" type="application/json">{_inline(scouts)}</script>')
    mermaid = (f'<script src="static/mermaid.min.js" nonce="{nonce}"></script>' if live else
               f'<script src="https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js" '
               f'integrity="{MERMAID_SRI}" crossorigin="anonymous"></script>')
    page = (page.replace("<!--FONTS-->", "" if live else FONTS)
                .replace("<!--MERMAID-->", mermaid)
                .replace("<!--INITIAL-->", initial)
                .replace("__NONCE__", nonce))
    if not live:
        return page
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '</head>\n<body>\n' + page + '</body>\n</html>\n')


def naming_the_export(root: Path, decl: Any) -> list[str]:
    """The declarations that name a file the export writes -- a component's `code:`, a test's run
    line or `reads:`, matched as staleness matches them -- and the declared tests whose latest run
    opened one. Evidence would rest on such a file, so the export writes nothing (DEF-live-board)."""
    from component_belief.readlog import read
    from component_belief.staleness import named_paths
    from component_belief.store import Store

    probe = {f"{EXPORT_DIR}/{name}" for name in EXPORT_FILES}
    hits = [cid for cid, comp in decl.components.items() if named_paths("", list(comp.code), probe)]
    hits += [tid for tid, test in decl.tests.items() if named_paths(test.run, list(test.reads), probe)]
    store = Store(root)
    for tid, run in store.latest_runs().items():
        if tid in decl.tests and any(p.split("/", 1)[0] == EXPORT_DIR for p in read(store.artifacts_dir / str(run))):
            hits.append(f"{tid} ({run})")
    return sorted(set(hits))


def export(root: Path, *, scouts: dict[str, Any] | None = None) -> str:
    """Write the board as it reads now to .research-board/: the page an Artifact publishes, the board's
    data, and a .gitignore keeping git out of the directory -- those three files and nothing else."""
    from ..board import build
    from ..data import board_data

    board = build(root)
    named = naming_the_export(root, board.decl)
    if named:
        return (f"nothing written: {', '.join(named)} name{'s' if len(named) == 1 else ''} a file in "
                f"{EXPORT_DIR}/, so evidence would rest on what the export writes there")
    data = board_data(board, mode="snapshot")
    directory = root / EXPORT_DIR
    directory.mkdir(exist_ok=True)
    (directory / ".gitignore").write_text("# written by research-board export; the board itself is in .research/\n*\n",
                                          encoding="utf-8")
    (directory / "board.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    (directory / "board.html").write_text(render(data, scouts), encoding="utf-8")
    short = (board.commit or "no commit")[:7]
    return (f"{EXPORT_DIR}/board.html: the board as of {board.now:%Y-%m-%d %H:%M} UTC at {short}, "
            f"{len(data['directions'])} directions{' and what the scouts did' if scouts else ''}. It is "
            "a page for a Claude Artifact; publish it only if the person asks, and keep it private unless "
            "they share it.")
