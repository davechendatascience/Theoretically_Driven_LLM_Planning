"""A constraint gate rebuilt on one rule: no change without an expectation
that could fail, and no evidence without a change."""

from .checks import prior_check
from .grammar import Unfalsifiable, admit, can_fail, evaluate, reduce_universal
from .invariants import Violation, check_all
from .migrate import migrate
from .models import (
    Change, Constraint, Expectation, FailureMode, Given, Goal, Intent, Objective, Outcome,
)
from .order import next_action, open_changes, open_constraints
from .store import Store

__all__ = [
    "Change", "Constraint", "Expectation", "FailureMode", "Given", "Goal",
    "Intent", "Objective", "Outcome", "Store", "Unfalsifiable", "Violation",
    "admit", "can_fail", "check_all", "evaluate", "migrate", "next_action",
    "open_changes", "open_constraints", "prior_check", "reduce_universal",
]
