"""research-board: the research board for a person to watch.

    research-board serve [--root .] [--port 8765] [--scouts claude-code]
        the board, live, in a browser on this machine
    research-board export [--root .] [--include-scouts]
        the board as of now, written to .research-board/ as a page a Claude Artifact can publish

Both read the board the research-board server keeps and decide nothing; neither records anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _scouts(args: argparse.Namespace, root: Path):
    from .live.scouts import ScoutWatch, project_folder

    return ScoutWatch([project_folder(root), *[Path(t).expanduser().resolve() for t in args.transcripts]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research-board", description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="the board, live, in a browser on this machine")
    serve.add_argument("--root", type=Path, default=Path.cwd(), help="the project (default: here)")
    serve.add_argument("--host", default="127.0.0.1", help="the address to bind (default 127.0.0.1: this machine only)")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--period", type=float, default=15.0, help="rebuild at least this often, in seconds")
    serve.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                       help="another name requests may address the server by (an SSH alias, a tunnel)")
    serve.add_argument("--scouts", choices=["claude-code"], default=None,
                       help="also show what research scouts are doing, from Claude Code's transcripts")
    serve.add_argument("--transcripts", action="append", default=[], metavar="DIR",
                       help="another Claude Code project folder to read scouts from (a worktree, a subdirectory)")

    export = commands.add_parser("export", help="write the board as of now to .research-board/ for an Artifact")
    export.add_argument("--root", type=Path, default=Path.cwd(), help="the project (default: here)")
    export.add_argument("--include-scouts", action="store_true",
                        help="include what the scouts did, from Claude Code's transcripts (left out by default)")
    export.add_argument("--transcripts", action="append", default=[], metavar="DIR")

    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "serve":
        from .live.server import serve as run

        run(root, args.host, args.port, args.period, args.allow_host,
            _scouts(args, root) if args.scouts else None)
        return 0
    from .live import export as write

    scouts = None
    if args.include_scouts:
        scouts = _scouts(args, root).poll()
        scouts.update(folders=[], empty="no scout has run" if not scouts["scouts"] else "")
    print(write(root, scouts=scouts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
