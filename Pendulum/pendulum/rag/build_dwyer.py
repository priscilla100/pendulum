"""Dwyer property-pattern corpus → chunks.

Source: data/dwyer_patterns.json (authored, committed). Each pattern×scope
entry becomes one chunk; the embedded text is the retrieval surface (intent +
example sentences), while the full entry — crucially `ltl_template` and
`placeholders` — rides along in metadata for the synthesis agent to use.
"""

from __future__ import annotations

import json
from pathlib import Path

from pendulum.config import PENDULUM_ROOT
from pendulum.rag.store import Chunk, RagError, corpus_hash

DWYER_JSON = PENDULUM_ROOT / "data" / "dwyer_patterns.json"

_REQUIRED_FIELDS = ("id", "pattern", "scope", "intent", "ltl_template", "placeholders", "example_nl")


def load_dwyer_chunks(path: Path = DWYER_JSON) -> tuple[list[Chunk], str]:
    """Returns (chunks, corpus_hash). Raises RagError on malformed entries."""
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise RagError(f"cannot read Dwyer corpus {path}: {exc}") from exc

    entries = data.get("patterns")
    if not isinstance(entries, list) or not entries:
        raise RagError(f"{path}: expected a non-empty 'patterns' array")

    chunks: list[Chunk] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(entries):
        missing = [f for f in _REQUIRED_FIELDS if f not in entry]
        if missing:
            raise RagError(f"{path}: entry {i} ({entry.get('id', '?')}) missing {missing}")
        if entry["id"] in seen_ids:
            raise RagError(f"{path}: duplicate id {entry['id']!r}")
        seen_ids.add(entry["id"])
        text = (
            f"{entry['pattern']} pattern, {entry['scope']} scope: {entry['intent']}\n"
            f"Examples: {' | '.join(entry['example_nl'])}"
        )
        chunks.append(Chunk(id=entry["id"], text=text, metadata=dict(entry)))
    return chunks, corpus_hash([raw])
