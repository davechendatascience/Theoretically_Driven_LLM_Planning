"""Data-directory resolution.

The server is bound to a single target project via DAMPED_PLAN_DATA_DIR,
which points at that project's `.damped-plan/` directory. Falls back to
`.damped-plan/` under the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "DAMPED_PLAN_DATA_DIR"


def data_dir() -> Path:
    raw = os.environ.get(ENV_DATA_DIR)
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd() / ".damped-plan"


def ensure_data_dir(path: Path | None = None) -> Path:
    root = path if path is not None else data_dir()
    (root / "plans").mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(parents=True, exist_ok=True)
    return root
