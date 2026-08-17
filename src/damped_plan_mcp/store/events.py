"""Append-only event log: every state transition, reproducible from artifacts.

One JSON object per line in events.jsonl:

    {"seq": 42, "ts": "...", "event": "constraint_status_changed",
     "actor": "mcp:update_constraint_status", "entity_type": "constraint",
     "entity_id": "C-0003", "data": {...}, "project_version": 7}

`seq` is monotone; callers append under the store lock. The Phase 5 drift
analyzer will consume `plan_status_changed` events unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def events_path(data_dir: Path) -> Path:
    return data_dir / "events.jsonl"


def last_seq(data_dir: Path) -> int:
    path = events_path(data_dir)
    if not path.exists():
        return 0
    seq = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    seq = max(seq, int(json.loads(line).get("seq", 0)))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    return seq


def append_event(
    data_dir: Path,
    event: str,
    actor: str,
    entity_type: str,
    entity_id: str,
    data: dict[str, Any] | None = None,
    project_version: int | None = None,
) -> dict[str, Any]:
    record = {
        "seq": last_seq(data_dir) + 1,
        "ts": datetime.now(UTC).isoformat(),
        "event": event,
        "actor": actor,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "data": data or {},
        "project_version": project_version,
    }
    path = events_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")
    return record


def read_events(data_dir: Path, limit: int | None = None) -> list[dict[str, Any]]:
    path = events_path(data_dir)
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records[-limit:] if limit else records
