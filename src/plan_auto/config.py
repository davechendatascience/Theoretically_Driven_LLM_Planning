"""Data-directory resolution.

The server is bound to a single target project via PLAN_AUTO_DATA_DIR, which
points at that project's `.plan-auto/` directory.

Backward compatibility: the project was previously named damped-plan and its
stores live in `.damped-plan/`. Five real project stores on record use that
name, so both the old env var and the old directory are still honoured — a
rename must not orphan a ledger. New projects get `.plan-auto/`; an existing
`.damped-plan/` keeps working untouched, and is preferred when it is the one
that actually exists.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "PLAN_AUTO_DATA_DIR"
LEGACY_ENV_DATA_DIR = "DAMPED_PLAN_DATA_DIR"

DIR_NAME = ".plan-auto"
LEGACY_DIR_NAME = ".damped-plan"


def resolve_data_dir(root: Path) -> Path:
    """Prefer the current name; fall back to the legacy one when it is what
    exists on disk. Neither present means a fresh project, which gets the
    current name."""
    current = root / DIR_NAME
    legacy = root / LEGACY_DIR_NAME
    if not current.exists() and legacy.exists():
        return legacy
    return current


def data_dir() -> Path:
    raw = os.environ.get(ENV_DATA_DIR) or os.environ.get(LEGACY_ENV_DATA_DIR)
    if raw:
        return Path(raw).expanduser().resolve()
    return resolve_data_dir(Path.cwd())


def ensure_data_dir(path: Path | None = None) -> Path:
    root = path if path is not None else data_dir()
    (root / "plans").mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(parents=True, exist_ok=True)
    return root
