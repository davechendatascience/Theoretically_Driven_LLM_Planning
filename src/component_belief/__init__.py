"""Component belief-update MCP.

Implements docs/component_belief_mcp_design.md. The load-bearing invariant:
there is no write path from an agent to a belief. Beliefs are a pure function
of (belief-eligible evidence, declared priors, model version).
"""

__version__ = "0.1.0"
MODEL_VERSION = "bb-1"
