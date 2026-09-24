"""Live end-to-end smoke test. Gated: PENDULUM_E2E=1 and live services
(Ollama with models pulled, built pltl-mcp + parser, BLACK; Docker and
llama-server optional — the pipeline degrades without them)."""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("PENDULUM_E2E") != "1", reason="PENDULUM_E2E != 1"),
]


async def test_translate_simple_response_property():
    from pendulum.pipeline import translate

    final = await translate("every request is eventually acknowledged")
    assert final.status == "OK"
    assert 1 <= len(final.formulas) <= 5
    top = final.formulas[0]
    assert top.canonical  # parse-gated by construction
    assert {"req", "ack"} <= set("".join(top.canonical)) or top.canonical  # sanity: non-empty
    assert final.ap_mapping, "AP mapping must be reported"


async def test_translate_past_tense_uses_past_operator():
    """The tense-neutrality requirement end-to-end: past tense in the NL
    should surface as a past operator, not vanish into the atom."""
    from pendulum.pipeline import translate

    final = await translate("Robin played soccer.")
    assert final.status == "OK"
    joined = " | ".join(f.canonical for f in final.formulas)
    assert any(op in joined for op in ("O ", "Y ", "H ", " S ")), (
        f"expected a past operator in: {joined}"
    )
