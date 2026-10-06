"""The same snapshot from a shell -- for a git hook, CI, or a person who wants the page now.

    graph-snapshot [--focus ID]
"""

from __future__ import annotations

import argparse
import sys

from . import take_snapshot
from .server import project_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graph-snapshot")
    parser.add_argument("--focus", default=None, help="the id the page opens on")
    args = parser.parse_args(argv)
    print(take_snapshot(project_root(), args.focus))
    return 0


if __name__ == "__main__":
    sys.exit(main())
