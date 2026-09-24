"""Lightweight vector store: numpy cosine over L2-normalized embeddings.

The corpora are small (tens to low hundreds of chunks), so brute-force cosine
is instant and transparent — no vector-DB dependency (user-decided fork).

On-disk layout per index directory:
    vectors.npz   float32 matrix, one L2-normalized row per chunk
    docs.json     [{id, text, metadata}, ...] in row order
    meta.json     {embed_model, corpus_hash, dim, count, version}

`meta.json` makes staleness detectable: an index is rebuilt when the corpus
content hash or the embedding model changes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

STORE_VERSION = 1


class RagError(Exception):
    """Index build/load/search failure."""


@dataclass
class Chunk:
    id: str
    text: str  # what gets embedded
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    chunk: Chunk
    score: float  # cosine similarity in [-1, 1]


_WORD = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens for BM25. Keeps operator names (`<->` becomes
    empty, but headings spell them: 'iff', 'until', 'releases', 'between')."""
    return _WORD.findall(text.lower())


def corpus_hash(parts: list[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(hashlib.sha256(part).digest())
    return digest.hexdigest()


class VectorStore:
    def __init__(self, vectors: np.ndarray, chunks: list[Chunk], meta: dict[str, Any]):
        if vectors.shape[0] != len(chunks):
            raise RagError(f"vector/chunk count mismatch: {vectors.shape[0]} vs {len(chunks)}")
        self._vectors = vectors
        self._chunks = chunks
        self.meta = meta

    def __len__(self) -> int:
        return len(self._chunks)

    # -- build / persist ----------------------------------------------------

    @classmethod
    def build(
        cls,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        *,
        embed_model: str,
        corpus_hash_: str,
    ) -> "VectorStore":
        if not chunks:
            raise RagError("cannot build an empty index")
        if len(embeddings) != len(chunks):
            raise RagError(f"{len(embeddings)} embeddings for {len(chunks)} chunks")
        matrix = np.asarray(embeddings, dtype=np.float32)
        if matrix.ndim != 2:
            raise RagError(f"embeddings must be 2-D, got shape {matrix.shape}")
        matrix = _l2_normalize(matrix)
        meta = {
            "version": STORE_VERSION,
            "embed_model": embed_model,
            "corpus_hash": corpus_hash_,
            "dim": int(matrix.shape[1]),
            "count": len(chunks),
        }
        return cls(matrix, chunks, meta)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(directory / "vectors.npz", vectors=self._vectors)
        docs = [{"id": c.id, "text": c.text, "metadata": c.metadata} for c in self._chunks]
        (directory / "docs.json").write_text(json.dumps(docs, ensure_ascii=False, indent=1))
        (directory / "meta.json").write_text(json.dumps(self.meta, indent=1))

    @classmethod
    def load(cls, directory: Path) -> "VectorStore":
        try:
            with np.load(directory / "vectors.npz") as npz:
                vectors = npz["vectors"]
            docs = json.loads((directory / "docs.json").read_text())
            meta = json.loads((directory / "meta.json").read_text())
        except (OSError, KeyError, ValueError) as exc:
            raise RagError(f"cannot load index from {directory}: {exc}") from exc
        chunks = [Chunk(id=d["id"], text=d["text"], metadata=d.get("metadata", {})) for d in docs]
        return cls(vectors, chunks, meta)

    @staticmethod
    def is_current(directory: Path, *, embed_model: str, corpus_hash_: str) -> bool:
        """True if a saved index exists and matches the corpus + embed model."""
        try:
            meta = json.loads((directory / "meta.json").read_text())
        except (OSError, ValueError):
            return False
        return (
            meta.get("version") == STORE_VERSION
            and meta.get("embed_model") == embed_model
            and meta.get("corpus_hash") == corpus_hash_
            and (directory / "vectors.npz").exists()
            and (directory / "docs.json").exists()
        )

    # -- search --------------------------------------------------------------

    def chunks_by_source(self, source: str) -> list[Chunk]:
        """All chunks whose metadata['source'] == source, in index order.
        Used to pin a whole condensed sub-corpus into context regardless of
        embedding-search ranking (SALT reference cards)."""
        return [c for c in self._chunks if c.metadata.get("source") == source]

    def search(self, query_vec: list[float], k: int) -> list[Hit]:
        if k <= 0:
            return []
        query = _l2_normalize(np.asarray([query_vec], dtype=np.float32))[0]
        scores = self._vectors @ query
        top = np.argsort(-scores)[: min(k, len(self._chunks))]
        return [Hit(chunk=self._chunks[i], score=float(scores[i])) for i in top]

    # -- hybrid (dense + keyword) search -------------------------------------

    def _dense_ranking(self, query_vec: list[float], idxs: list[int]) -> list[int]:
        query = _l2_normalize(np.asarray([query_vec], dtype=np.float32))[0]
        scores = self._vectors @ query
        return sorted(idxs, key=lambda i: -scores[i])

    def _keyword_ranking(self, terms: list[str], idxs: list[int]) -> list[int]:
        """BM25 ranking of `idxs` by the query `terms`. Corpus is tiny, so
        stats are computed on the fly. Fixes lexical misses where an operator
        name in the query should match a heading/card that dense embeddings
        rank poorly (RAG-retrieval test, 2026-07-06)."""
        qterms = [t for t in (_tokenize(" ".join(terms))) if t]
        if not qterms or not idxs:
            return list(idxs)
        docs = {i: _tokenize(self._chunks[i].text) for i in idxs}
        N = len(idxs)
        avg_len = sum(len(d) for d in docs.values()) / N or 1.0
        df: dict[str, int] = {}
        for d in docs.values():
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        import math
        k1, b = 1.5, 0.75
        def score(i: int) -> float:
            d = docs[i]; dl = len(d) or 1; s = 0.0
            counts = {t: d.count(t) for t in set(qterms) if t in d}
            for t, f in counts.items():
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avg_len))
            return s
        return sorted(idxs, key=lambda i: -score(i))

    def hybrid_search(
        self, query_vec: list[float], terms: list[str], k: int,
        *, sources: Optional[tuple[str, ...]] = None, rrf_k: int = 60,
    ) -> list[Hit]:
        """Reciprocal-rank fusion of dense + BM25 rankings. `sources` optionally
        restricts to chunks from those metadata['source'] values (e.g. the
        condensed cards only, dropping verbose PDF noise). RRF needs no score
        normalization: fused = sum 1/(rrf_k + rank) across the two rankings."""
        if k <= 0:
            return []
        idxs = [i for i, c in enumerate(self._chunks)
                if sources is None or c.metadata.get("source") in sources]
        if not idxs:
            return []
        dense = self._dense_ranking(query_vec, idxs)
        kw = self._keyword_ranking(terms, idxs)
        fused: dict[int, float] = {}
        for rank, i in enumerate(dense):
            fused[i] = fused.get(i, 0.0) + 1.0 / (rrf_k + rank)
        for rank, i in enumerate(kw):
            fused[i] = fused.get(i, 0.0) + 1.0 / (rrf_k + rank)
        top = sorted(idxs, key=lambda i: -fused[i])[: min(k, len(idxs))]
        return [Hit(chunk=self._chunks[i], score=round(fused[i], 5)) for i in top]


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0  # zero vectors stay zero instead of dividing by 0
    return matrix / norms
