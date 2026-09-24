"""Corpus builders: Dwyer JSON validation, SALT section splitting + timed filter."""

from __future__ import annotations

import json

import pytest

from pendulum.rag.build_dwyer import load_dwyer_chunks
from pendulum.rag.build_salt import _TIMED_RE, build_salt_chunks
from pendulum.rag.store import RagError

DWYER_ENTRY = {
    "id": "response_global",
    "pattern": "Response",
    "scope": "Global",
    "intent": "S responds to P globally.",
    "ltl_template": "G (p -> F s)",
    "placeholders": ["p", "s"],
    "example_nl": ["every request is eventually acknowledged"],
}


class TestDwyerLoader:
    def write(self, tmp_path, patterns):
        path = tmp_path / "dwyer.json"
        path.write_text(json.dumps({"version": 1, "patterns": patterns}))
        return path

    def test_valid_corpus(self, tmp_path):
        chunks, digest = load_dwyer_chunks(self.write(tmp_path, [DWYER_ENTRY]))
        assert len(chunks) == 1 and len(digest) == 64
        chunk = chunks[0]
        assert "Response pattern, Global scope" in chunk.text
        assert "every request" in chunk.text  # examples are embedded
        assert chunk.metadata["ltl_template"] == "G (p -> F s)"  # template rides in metadata

    def test_missing_field_rejected(self, tmp_path):
        broken = {k: v for k, v in DWYER_ENTRY.items() if k != "ltl_template"}
        with pytest.raises(RagError, match="missing .*ltl_template"):
            load_dwyer_chunks(self.write(tmp_path, [broken]))

    def test_duplicate_id_rejected(self, tmp_path):
        with pytest.raises(RagError, match="duplicate id"):
            load_dwyer_chunks(self.write(tmp_path, [DWYER_ENTRY, DWYER_ENTRY]))

    def test_empty_and_missing_rejected(self, tmp_path):
        with pytest.raises(RagError, match="non-empty"):
            load_dwyer_chunks(self.write(tmp_path, []))
        with pytest.raises(RagError, match="cannot read"):
            load_dwyer_chunks(tmp_path / "nope.json")


SALT_HELP = """\
================================================================
SALT SPEC GRAMMAR (condensed)
================================================================

TOP-LEVEL SHAPE
  assert <expression>

FUTURE TEMPORAL OPERATORS
  always x, eventually x

TIMED OPERATORS
  this section is about timed SALT with timeunit annotations
"""

SALT_README = """\
# SALT

## 1. Running SALT

### 1.1 Container
docker stuff (not indexed)

## 3. SALT syntax reference (untimed only)

### 3.1 Top-level shape
assert always p

### 3.2 Boolean layer
and, or, not

## 4. Translation patterns

### 4.1 Anti-patterns
prefer plain assertions over clever regex tricks.

## 5. Suggested tool surface

### 5.1 Not indexed
should not appear
"""


class TestSaltBuilder:
    def test_sections_split_curated_not_timed_filtered(self, tmp_path):
        help_txt = tmp_path / "help.txt"
        help_txt.write_text(SALT_HELP)
        readme = tmp_path / "README.md"
        readme.write_text(SALT_README)
        chunks, digest, dropped = build_salt_chunks(
            help_txt, readme, tmp_path / "absent.pdf", include_pdf=False
        )
        titles = [c.metadata["section"] for c in chunks]
        assert any("TOP-LEVEL SHAPE" in t for t in titles)
        assert any("FUTURE TEMPORAL" in t for t in titles)
        # curated sources are untimed-only by construction — indexed in full,
        # even when a section title/body happens to contain a timed marker
        # (the timed filter applies to PDF chunks only)
        assert any("TIMED OPERATORS" in t for t in titles)
        assert dropped == 0
        # readme: only §3.x / §4.x subsections, not §1 or §5
        assert any("3.1" in t for t in titles) and any("4.1" in t for t in titles)
        assert not any("1.1" in t or "5.1" in t for t in titles)
        assert len(digest) == 64

    def test_missing_pdf_is_fine_but_missing_text_sources_raise(self, tmp_path):
        help_txt = tmp_path / "help.txt"
        help_txt.write_text(SALT_HELP)
        readme = tmp_path / "README.md"
        readme.write_text(SALT_README)
        chunks, _, _ = build_salt_chunks(help_txt, readme, tmp_path / "absent.pdf")
        assert chunks  # PDF optional
        with pytest.raises(RagError, match="cannot read"):
            build_salt_chunks(tmp_path / "nope.txt", readme, tmp_path / "absent.pdf")

    def test_timed_regex_boundaries(self):
        assert _TIMED_RE.search("the timed extension")
        assert _TIMED_RE.search("set a timeunit of seconds")
        assert _TIMED_RE.search("holds within[=3.0] of the event")  # timed operator form
        # plain-English 'within' and untimed scope operators must NOT match
        assert not _TIMED_RE.search("within the scope of the assertion")
        assert not _TIMED_RE.search("p upto q and between q and r, then nextn[3]")
