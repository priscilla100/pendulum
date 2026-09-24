"""SALT_TO_LTL — synthesis through the SALT compiler.

Deterministic scaffold: retrieve SALT-manual excerpts from the RAG index, let
the LLM author a SALT spec, compile it with the nl_to_ltl_via_salt MCP tool
(Docker), and — on compiler error — feed the error text back for a bounded
fix loop (SALT_FIX_MAX_ATTEMPTS, task.md requirement). The compiled LTL then
passes the usual parser gate + confidence emission.
"""

from __future__ import annotations

import re
import time

from pendulum.agents.emission import CandidateInvalid, make_candidate
from pendulum.agents.envelope import AgentEnvelope, error_envelope, ok_envelope
from pendulum.agents.formatting import ap_block
from pendulum.agents.parsing import strip_code_fences
from pendulum.deps import PendulumDeps
from pendulum.llm.base import LlmError, Message
from pendulum.mcp.client import McpError, McpToolError
from pendulum.prompt_loader import load, render
from pendulum.schemas import APMapping, Candidate

_REFERENCE_CHAR_CAP = 18000  # fits the full condensed reference (~15k) + supplements; models have >=32k ctx

#: SALT 1.0.1 reserved keywords (from the salt_help reference, which says
#: "do NOT use as variable names — mangle them"). Quoted atoms are NOT a
#: workaround: the shipped compiler mishandles quote escaping (verified —
#: `declare "req"` and quoted infix operands both fail to parse).
_SALT_RESERVED = frozenset("""
assert define declare true false
always never eventually next until releases
historically once since triggered previous
alwaysinpast eventuallyinpast neverinpast untilinpast releasesinpast
nextinpast frominpast uptoinpast betweeninpast occurringinpast
holdinginpast nextninpast previousn
upto before from after between rejecton accepton
occurring holding nextn
req opt weak incl excl required optional inclusive exclusive
and or not implies equals
if then else
allof noneof someof exactlyoneof in as list enumerate with without
timed
""".split())


def _mangle_reserved(aps: list[APMapping]) -> tuple[list[APMapping], dict[str, str]]:
    """Rename reserved-colliding atoms for the SALT spec (e.g. req → req_ap);
    returns (renamed mappings for the prompt, {mangled: original} to undo it
    on the compiled LTL). Deterministic and collision-safe."""
    taken = {m.ap for m in aps}
    renamed: list[APMapping] = []
    inverse: dict[str, str] = {}
    for m in aps:
        name = m.ap
        if name in _SALT_RESERVED:
            candidate = f"{name}_ap"
            while candidate in taken or candidate in _SALT_RESERVED:
                candidate += "x"
            taken.add(candidate)
            inverse[candidate] = name
            name = candidate
        renamed.append(APMapping(ap=name, nl_fragment=m.nl_fragment, polarity=m.polarity))
    return renamed, inverse


def _unmangle(formula: str, inverse: dict[str, str]) -> str:
    if not inverse:
        return formula
    return re.sub(
        r"\b[a-z][a-z0-9_]*\b",
        lambda match: inverse.get(match.group(), match.group()),
        formula,
    )


def _conjoin_ltlspecs(ltl: str) -> str:
    """A spec with N assert lines compiles to N LTLSPEC formulas; the tool
    strips the first prefix but later lines arrive as 'LTLSPEC <f>'. Multiple
    asserts ARE a conjunction in SALT semantics, so conjoin them (user-approved
    fix, 2026-07-04)."""
    parts = [re.sub(r"^\s*LTLSPEC\s+", "", line).strip()
             for line in ltl.splitlines() if line.strip()]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return parts[0] if parts else ltl
    return " & ".join(f"({p})" for p in parts)


#: SALT-vocabulary terms the reformulation query may name — matched against
#: the operator-card headings by the BM25 half of hybrid retrieval.
_FEATURE_VOCAB = (
    "always never eventually until until-weak releases next once historically "
    "since previous biconditional iff implies and or not between upto from "
    "next-chain scope reserved-keyword"
)

_FEATURE_PROMPT = (
    "You are picking SALT reference sections to look up. Given a requirement, "
    "list ONLY the SALT operator/feature keywords needed to formalize it, "
    "chosen from: " + _FEATURE_VOCAB + ". Reply with a short comma-separated "
    "list of keywords, nothing else.\n\nRequirement: {nl}"
)


def _tokenize_terms(terms: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,\s]+", terms) if t.strip()]


async def _salt_feature_terms(nl: str, deps: PendulumDeps) -> str:
    """One cheap completion turning the NL requirement into SALT-vocabulary
    search terms (e.g. 'biconditional, always') that match the operator-card
    headings — the query regime where retrieval succeeds. Degrades to the raw
    NL on any failure so retrieval never breaks."""
    try:
        result = await deps.router.complete(
            deps.agent_cfg("SALT"),
            [{"role": "user", "content": _FEATURE_PROMPT.format(nl=nl)}],
            want_logprobs=False, max_tokens=64,
        )
        terms = result.text.strip().splitlines()[0] if result.text.strip() else ""
        deps.logger.debug("synth_salt", "feature_terms", terms=terms)
        return terms or nl
    except LlmError as exc:
        deps.logger.warning("synth_salt", "feature_terms_failed", error=str(exc))
        return nl


async def synthesize_salt(
    nl: str, aps: list[APMapping], deps: PendulumDeps, feedback: str = "", round_: int = 0
) -> AgentEnvelope[list[Candidate]]:
    started = time.monotonic()
    try:
        envelope = await _run(nl, aps, deps, feedback, round_)
    except (LlmError, McpError) as exc:
        deps.logger.error("synth_salt", "failed", error=str(exc))
        envelope = error_envelope(str(exc))
    envelope.elapsed_s = round(time.monotonic() - started, 2)
    return envelope


async def _run(
    nl: str, aps: list[APMapping], deps: PendulumDeps, feedback: str, round_: int
) -> AgentEnvelope[list[Candidate]]:
    if deps.config.salt_rag_disabled:
        # RAG off (exp-19 A/B): no retrieval at all — the static system prompt
        # carries the guidance, so skip the index requirement entirely and hand
        # the author an empty reference block.
        reference = ""
        deps.logger.info("synth_salt", "reference_retrieved", mode="off", sections=[])
    else:
        if deps.rag is None or deps.embedder is None:
            return error_envelope("SALT RAG index not initialized (run `python -m pendulum init-rag`)")

        if deps.config.salt_hybrid_retrieval:
            # Hybrid (dense + BM25 via RRF) over the CONDENSED cards only, with an
            # LLM-reformulated SALT-vocabulary query. Targets the retrieval-quality
            # misses the RAG test found (operator cards buried under PDF noise;
            # NL-vocabulary queries not matching operator headings).
            terms = await _salt_feature_terms(nl, deps)
            query_vec = await deps.embedder.embed_one(f"{nl}\nSALT features: {terms}")
            hits = deps.rag.salt.hybrid_search(
                query_vec, _tokenize_terms(terms), max(deps.config.rag_top_k, 6),
                sources=("salt_help", "salt_readme"),
            )
            chunks = [h.chunk for h in hits]
            mode = "hybrid"
        else:
            query_vec = await deps.embedder.embed_one(nl)
            if deps.config.salt_pin_condensed_reference:
                # Pin the full condensed reference (all salt_help operator cards):
                # small (~3.8k tokens) and otherwise buried under verbose PDF chunks
                # (RAG-retrieval test, 2026-07-06). Retrieval supplements with the
                # best verbose manual/README hits not already pinned.
                pinned = deps.rag.salt.chunks_by_source("salt_help")
                pinned_ids = {c.id for c in pinned}
                hits = deps.rag.salt.search(query_vec, deps.config.rag_top_k)
                chunks = pinned + [h.chunk for h in hits if h.chunk.id not in pinned_ids]
            else:
                hits = deps.rag.salt.search(query_vec, deps.config.rag_top_k)
                chunks = [h.chunk for h in hits]
            mode = "pinned" if deps.config.salt_pin_condensed_reference else "dense"
        reference = "\n\n".join(c.text for c in chunks)[:_REFERENCE_CHAR_CAP]
        deps.logger.info(
            "synth_salt", "reference_retrieved", mode=mode,
            sections=[c.metadata.get("section", c.id) for c in chunks],
        )

    cfg = deps.agent_cfg("SALT")
    salt_aps, inverse = _mangle_reserved(aps)
    if inverse:
        deps.logger.info("synth_salt", "reserved_atoms_mangled", renames=inverse)
    user = render(
        "salt_author_user",
        SALT_REFERENCE=reference,
        NATURAL_LANGUAGE=nl,
        ATOMIC_PROPOSITIONS=ap_block(salt_aps),
    )
    if feedback:
        user = feedback + "\n" + user
    messages: list[Message] = [
        {"role": "system", "content": load("salt_author_system")},
        {"role": "user", "content": user},
    ]

    attempts = deps.config.salt_fix_max_attempts
    for attempt in range(1, attempts + 1):
        result = await deps.router.complete(cfg, messages, want_logprobs=False)
        spec = strip_code_fences(result.text)
        deps.logger.debug("synth_salt", "spec_authored", attempt=attempt, spec=spec)

        try:
            compiled = await deps.mcp.nl_to_ltl_via_salt(spec)
            ok, ltl, error = compiled.ok, compiled.ltl, compiled.error
        except McpToolError as exc:  # server-side rejection == compile feedback
            ok, ltl, error = False, None, exc.server_message

        if ok and ltl:
            try:
                candidate = await make_candidate(
                    deps, source_agent="salt", formula=_unmangle(_conjoin_ltlspecs(ltl), inverse),
                    rationale=f"SALT compiled from spec: {spec[:300]}",
                    index=attempt, attempts=attempt, round_=round_,
                )
                deps.logger.info("synth_salt", "candidate", formula=candidate.canonical, attempt=attempt)
                return ok_envelope([candidate], attempts=attempt)
            except CandidateInvalid as exc:
                error = f"compiler output {ltl!r} was rejected by the LTL parser: {exc}"

        deps.logger.warning("synth_salt", "compile_failed_retrying", attempt=attempt, error=error)
        messages.append({"role": "assistant", "content": spec})
        messages.append({
            "role": "user",
            "content": render("salt_fix_user", SPEC=spec, COMPILE_ERROR=error or "unknown compiler error"),
        })

    return error_envelope(f"SALT compilation failed after {attempts} attempts", attempts=attempts)
