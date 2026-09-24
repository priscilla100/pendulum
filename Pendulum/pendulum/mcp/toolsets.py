"""Named tool groups of the pltl-mcp catalogue (exactly 14 tools).

The cache split implements a user requirement: results of DETERMINISTIC tools
(pure functions of their arguments — parser, SALT compiler, static reference,
BLACK solver) may be cached client-side; LLM-backed FUZZY tools must never be.
`check_trace_satisfaction` sits on the boundary: the satisfaction check is
BLACK-deterministic, but `explain=true` adds a helper-LLM explanation — so its
cacheability depends on the arguments (see `is_cacheable`).
"""

from __future__ import annotations

from typing import Any, Mapping

#: The 8 BLACK-solver tools — the deterministic verifier's (and orchestrator's) toolset.
BLACK_TOOLS = frozenset({
    "check_equivalence",
    "check_entailment",
    "check_consistency",
    "compare_candidates",
    "gen_satisfying_trace",
    "gen_violating_trace",
    "distinguishing_trace",
    "check_trace_satisfaction",
})

#: LLM-backed tools — never cached, never given to the deterministic verifier.
FUZZY_TOOLS = frozenset({
    "extract_ap_mapping",
    "nl_to_ltl_via_python",
    "ltl_to_nl",
})

#: Deterministic non-BLACK tools.
_OTHER_DETERMINISTIC = frozenset({
    "parse_and_canonicalize",
    "nl_to_ltl_via_salt",  # the SALT compiler is a pure function of the spec
    "salt_help",
})

ALL_TOOLS = BLACK_TOOLS | FUZZY_TOOLS | _OTHER_DETERMINISTIC
assert len(ALL_TOOLS) == 14, "pltl-mcp catalogue is exactly 14 tools"

CACHEABLE_TOOLS = BLACK_TOOLS | _OTHER_DETERMINISTIC


def is_cacheable(tool: str, args: Mapping[str, Any]) -> bool:
    """May this call's result be cached? Deterministic tools only."""
    if tool not in CACHEABLE_TOOLS:
        return False
    if tool == "check_trace_satisfaction" and args.get("explain"):
        return False  # explain=true routes through the helper LLM
    return True
