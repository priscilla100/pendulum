"""SALT-manual corpus → chunks, from three tiers of source material:

1. mcp/server/src/tools/salt_help_content.txt — the condensed reference the
   salt_help tool serves (sectioned by ==== banners + ALL-CAPS headings);
2. vendor/salt/README.md §3 (untimed syntax reference) and §4 (NL→SALT→LTL
   translation patterns) — chunked per ### subsection;
3. vendor/salt/salt_extract/manual.pdf — the official SALT 1.0.1 manual via
   pypdf, paragraph-packed to ~800 chars.

The pipeline compiles with -notimed, so timed-SALT material is actively
misleading. The curated tiers (1-2) are purpose-written UNTIMED-ONLY, so they
are indexed in full; the official manual covers timed SALT too, so PDF chunks
matching the timed-marker regex are DROPPED at build time (counted and logged
by the caller). PDF text is supplementary and noisier by nature.
"""

from __future__ import annotations

import re
from pathlib import Path

from pendulum.config import REPO_ROOT
from pendulum.rag.store import Chunk, RagError, corpus_hash

SALT_HELP_TXT = REPO_ROOT / "mcp" / "server" / "src" / "tools" / "salt_help_content.txt"
SALT_README = REPO_ROOT / "vendor" / "salt" / "README.md"
SALT_MANUAL_PDF = REPO_ROOT / "vendor" / "salt" / "salt_extract" / "manual.pdf"

#: Timed-SALT markers, applied to PDF chunks only. Deliberately narrow:
#: 'timed'/'timeunit' reliably mark the manual's timed chapters, and
#: 'within[' is the timed operator's bracket form. Plain English 'within'
#: and the untimed scope ops (upto/between/nextn) must NOT match.
_TIMED_RE = re.compile(
    r"\btimed\b|\btimeunit\b|\bexactlyontime\b|\bwithin\s*\[", re.IGNORECASE
)

# A heading = non-indented line beginning with an ALL-CAPS word of >=4 chars
# (headings like "SCOPE OPERATORS — `upto`..." carry lowercase tails).
_CAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9/'-]{3,}(\s.*)?$")
_BANNER = re.compile(r"^={4,}\s*$")


def build_salt_chunks(
    help_txt: Path = SALT_HELP_TXT,
    readme: Path = SALT_README,
    manual_pdf: Path = SALT_MANUAL_PDF,
    *,
    include_pdf: bool = True,
) -> tuple[list[Chunk], str, int]:
    """Returns (chunks, corpus_hash, dropped_timed_count)."""
    hash_parts: list[bytes] = []
    chunks: list[Chunk] = []
    dropped = 0

    help_bytes = _read(help_txt)
    hash_parts.append(help_bytes)
    for i, (title, body) in enumerate(_split_caps_sections(help_bytes.decode("utf-8"))):
        chunks.append(Chunk(
            id=f"salthelp-{i:02d}",
            text=f"[SALT condensed reference — {title}]\n{body}",
            metadata={"source": "salt_help", "section": title},
        ))

    readme_bytes = _read(readme)
    hash_parts.append(readme_bytes)
    for i, (title, body) in enumerate(_split_readme_sections(readme_bytes.decode("utf-8"))):
        chunks.append(Chunk(
            id=f"saltreadme-{i:02d}",
            text=f"[SALT reference — {title}]\n{body}",
            metadata={"source": "salt_readme", "section": title},
        ))

    if include_pdf and manual_pdf.exists():
        pdf_bytes = manual_pdf.read_bytes()
        hash_parts.append(pdf_bytes)
        for i, paragraph in enumerate(_pdf_paragraphs(manual_pdf)):
            if _TIMED_RE.search(paragraph):
                dropped += 1
                continue
            chunks.append(Chunk(
                id=f"saltmanual-{i:03d}",
                text=f"[SALT official manual]\n{paragraph}",
                metadata={"source": "salt_manual_pdf"},
            ))

    if not chunks:
        raise RagError("SALT corpus produced zero chunks — sources missing?")
    return chunks, corpus_hash(hash_parts), dropped


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RagError(f"cannot read SALT source {path}: {exc}") from exc


def _split_caps_sections(text: str):
    """salt_help_content.txt: ALL-CAPS headings inside ==== banner sections.

    Banner titles (the line between two ==== lines) become the section prefix
    for content until the next heading."""
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    banner_title = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        if _BANNER.match(line) and i + 2 < len(lines) and _BANNER.match(lines[i + 2]):
            banner_title = lines[i + 1].strip()
            sections.append((banner_title, []))
            i += 3
            continue
        if _CAPS_HEADING.match(line):  # anchored: leading indentation disqualifies
            title = line.strip()
            sections.append((f"{banner_title}: {title}" if banner_title else title, []))
        elif sections:
            sections[-1][1].append(line)
        i += 1
    return [(title, "\n".join(body).strip()) for title, body in sections if "\n".join(body).strip()]


def _split_readme_sections(text: str):
    """vendor/salt/README.md: keep §3.x and §4.x subsections only."""
    sections: list[tuple[str, list[str]]] = []
    keep = False
    for line in text.splitlines():
        heading = re.match(r"^(#{2,3})\s+(.*)$", line)
        if heading:
            title = heading.group(2).strip()
            top_level = re.match(r"^([0-9]+)", title)
            if heading.group(1) == "##" and top_level:
                keep = top_level.group(1) in ("3", "4")
            if keep:
                sections.append((title, []))
            continue
        if keep and sections:
            sections[-1][1].append(line)
    return [(title, "\n".join(body).strip()) for title, body in sections if "\n".join(body).strip()]


def _pdf_paragraphs(pdf_path: Path, target_chars: int = 800):
    """Extract text with pypdf and pack paragraphs to ~target_chars pieces."""
    try:
        import logging

        logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-dict warnings are noise
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 — any pypdf failure degrades to no-PDF
        raise RagError(f"PDF extraction failed for {pdf_path}: {exc}") from exc

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", "\n\n".join(pages)) if p.strip()]
    packed: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if len(candidate) > target_chars and current:
            packed.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed
