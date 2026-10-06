"""What changed between two inventories of blocks.

A block is matched by its id. Its location is where it was found, so a block whose body and
relations are the same and whose path or lines differ only moved. A body change and a relation
change are reported apart, because they ask for different reviews: the first, whether the code
still realizes its claims; the second, whether the claims it now names are the right ones.

This is the transient view -- what one range of commits did. The persistent one is the pins
(validation.py): a body change reported here and never re-reviewed is still reported there, at
every later revision, until someone updates its pin.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Block, CodeIndex

ADDED, REMOVED, MOVED, BODY, RELATIONS, REPINNED, RENAMED = (
    "added", "removed", "moved", "body", "relations", "repinned", "renamed")


@dataclass(frozen=True)
class BlockChange:
    block_id: str
    change: str
    detail: str
    path: str
    targets: tuple[str, ...] = ()


@dataclass
class Changes:
    base: str
    head: str
    items: list[BlockChange] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)    # claims whose last implements link went

    def of(self, change: str) -> list[BlockChange]:
        return [c for c in self.items if c.change == change]

    def __bool__(self) -> bool:
        return bool(self.items or self.orphaned)


def _unique(blocks: list[Block]) -> dict[str, Block]:
    seen: dict[str, list[Block]] = {}
    for b in blocks:
        seen.setdefault(b.block_id, []).append(b)
    return {bid: group[0] for bid, group in seen.items() if len(group) == 1}


def compare_indexes(previous: CodeIndex, current: CodeIndex) -> Changes:
    """Changes from `previous` to `current`. When `previous` covers only some paths, `current`
    is compared on those paths alone; orphaned claims are judged only against a full `current`,
    since a claim's other links may live anywhere."""
    changes = Changes(previous.revision, current.revision)
    scope = previous.scope.paths
    before = _unique(previous.blocks)
    now_all = _unique(current.blocks)
    now = now_all if scope is None else {
        bid: b for bid, b in now_all.items() if b.path in scope or bid in before}

    def targets(b: Block) -> tuple[str, ...]:
        return tuple(sorted(b.targets()))

    for bid in sorted(set(before) - set(now)):
        b = before[bid]
        changes.items.append(BlockChange(bid, REMOVED, f"was {b.location}", b.path, targets(b)))
    added = sorted(set(now) - set(before))
    for bid in added:
        b = now[bid]
        twin = [r for r in set(before) - set(now) if before[r].body_hash == b.body_hash]
        if twin:
            changes.items.append(BlockChange(bid, RENAMED, f"same body as removed {twin[0]}",
                                             b.path, targets(b)))
        changes.items.append(BlockChange(bid, ADDED, f"at {b.location}", b.path, targets(b)))

    for bid in sorted(set(before) & set(now)):
        old, new = before[bid], now[bid]
        if old.body_hash != new.body_hash:
            changes.items.append(BlockChange(bid, BODY, f"its code changed at {new.location}",
                                             new.path, targets(new)))
        if old.relation_set() != new.relation_set():
            gone = sorted(old.relation_set() - new.relation_set())
            came = sorted(new.relation_set() - old.relation_set())
            detail = "; ".join(filter(None, [
                "dropped " + ", ".join(f"{k} {t}" for k, t in gone) if gone else "",
                "added " + ", ".join(f"{k} {t}" for k, t in came) if came else ""]))
            changes.items.append(BlockChange(bid, RELATIONS, detail, new.path, targets(new)))
        old_pins = (old.pin, {(r.kind, r.target): r.pin for r in old.relations})
        new_pins = (new.pin, {(r.kind, r.target): r.pin for r in new.relations})
        if old_pins != new_pins and old.relation_set() == new.relation_set():
            changes.items.append(BlockChange(bid, REPINNED, "its pins were rewritten: a review was "
                                             "asserted in this range", new.path, targets(new)))
        # moved: it starts somewhere else. A header that gained or lost a line ends elsewhere
        # without having moved, and a body that grew is a body change.
        if (old.path, old.start_line) != (new.path, new.start_line) and old.body_hash == new.body_hash:
            changes.items.append(BlockChange(bid, MOVED, f"{old.location} -> {new.location}",
                                             new.path, targets(new)))

    if current.scope.paths is None:
        def implemented(blocks: dict[str, Block]) -> set[str]:
            return {r.target for b in blocks.values() if b.valid for r in b.relations
                    if r.kind == "implements"}
        changes.orphaned = sorted(implemented(before) - implemented(now_all))
    return changes
