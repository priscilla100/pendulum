"""Length-Normalized Log-Likelihood.

LNLL(completion) = (1/N) * sum(log P(token_i))  — the mean token logprob.
0.0 means the model was certain of every token; more negative = less certain.

Caveats (why the orchestrator treats this as a SECONDARY signal, tie-break
only): it measures fluency, not correctness; values are not comparable across
models with different tokenizers; grammar-constrained decoding renormalizes
the distribution over the few grammar-legal tokens, inflating the values.
"""

from __future__ import annotations

from typing import Optional, Sequence


def compute_lnll(token_logprobs: Optional[Sequence[float]]) -> Optional[float]:
    """Mean of the token logprobs; None for missing or empty input."""
    if not token_logprobs:
        return None
    return sum(token_logprobs) / len(token_logprobs)
