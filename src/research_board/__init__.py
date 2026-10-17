"""research-board: research directions for a goal, the papers behind them, and what was spent
testing them.

component-belief says whether the built thing works and consistency-belief whether the design
follows. Neither says what is worth trying next, or keeps the reading that suggested it. This
package keeps that as a game with one rule that matters: research is free and earns points for a
direction, building and testing for a direction costs points, and a result counts for a direction
only when the points were spent on it before the run (DEF-research-ledger). Working without the
board stays free; its results simply belong to no direction.

The rules live in research.yaml, read from git HEAD like every declaration. The play -- directions,
trails, spends and feedback -- is an append-only ledger in .research/, and the board is a page
beside it, rewritten on every write. Nothing here writes to either of the other ledgers or to a
declaration: a direction's results are read from component-belief, never recorded by this server.
"""

from __future__ import annotations
