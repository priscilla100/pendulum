"""VectorStore: build/save/load round-trip, cosine ordering, staleness."""

from __future__ import annotations

import pytest

from pendulum.rag.store import Chunk, RagError, VectorStore, corpus_hash


def make_store():
    chunks = [Chunk(id="a", text="alpha"), Chunk(id="b", text="beta"), Chunk(id="c", text="gamma")]
    embeddings = [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]]
    return VectorStore.build(chunks, embeddings, embed_model="m", corpus_hash_="h1")


class TestBuildAndSearch:
    def test_cosine_ordering(self):
        store = make_store()
        hits = store.search([1.0, 0.1], k=3)
        assert [h.chunk.id for h in hits] == ["a", "c", "b"]
        assert hits[0].score > hits[1].score > hits[2].score

    def test_k_bounds(self):
        store = make_store()
        assert len(store.search([1.0, 0.0], k=2)) == 2
        assert len(store.search([1.0, 0.0], k=99)) == 3
        assert store.search([1.0, 0.0], k=0) == []

    def test_build_validation(self):
        with pytest.raises(RagError, match="empty"):
            VectorStore.build([], [], embed_model="m", corpus_hash_="h")
        with pytest.raises(RagError, match="embeddings for"):
            VectorStore.build([Chunk(id="a", text="t")], [], embed_model="m", corpus_hash_="h")

    def test_zero_vector_does_not_crash(self):
        store = VectorStore.build(
            [Chunk(id="a", text="t"), Chunk(id="z", text="zero")],
            [[1.0, 0.0], [0.0, 0.0]],
            embed_model="m", corpus_hash_="h",
        )
        hits = store.search([1.0, 0.0], k=2)
        assert hits[0].chunk.id == "a"


class TestPersistence:
    def test_round_trip(self, tmp_path):
        store = make_store()
        store.save(tmp_path / "idx")
        loaded = VectorStore.load(tmp_path / "idx")
        assert len(loaded) == 3 and loaded.meta == store.meta
        assert [h.chunk.id for h in loaded.search([0.0, 1.0], k=1)] == ["b"]

    def test_metadata_survives(self, tmp_path):
        chunks = [Chunk(id="x", text="t", metadata={"ltl_template": "G (p -> F s)"})]
        store = VectorStore.build(chunks, [[1.0, 0.0]], embed_model="m", corpus_hash_="h")
        store.save(tmp_path / "idx")
        loaded = VectorStore.load(tmp_path / "idx")
        assert loaded.search([1.0, 0.0], k=1)[0].chunk.metadata["ltl_template"] == "G (p -> F s)"

    def test_load_missing_raises(self, tmp_path):
        with pytest.raises(RagError, match="cannot load"):
            VectorStore.load(tmp_path / "nope")


class TestStaleness:
    def test_current_index_detected(self, tmp_path):
        make_store().save(tmp_path / "idx")
        assert VectorStore.is_current(tmp_path / "idx", embed_model="m", corpus_hash_="h1")

    def test_hash_or_model_change_invalidates(self, tmp_path):
        make_store().save(tmp_path / "idx")
        assert not VectorStore.is_current(tmp_path / "idx", embed_model="m", corpus_hash_="h2")
        assert not VectorStore.is_current(tmp_path / "idx", embed_model="other", corpus_hash_="h1")

    def test_missing_dir_not_current(self, tmp_path):
        assert not VectorStore.is_current(tmp_path / "nope", embed_model="m", corpus_hash_="h1")

    def test_corpus_hash_order_sensitive(self):
        assert corpus_hash([b"a", b"b"]) != corpus_hash([b"b", b"a"])


class TestHybridSearch:
    def _store(self):
        import numpy as np
        from pendulum.rag.store import VectorStore, Chunk
        chunks = [
            Chunk("salthelp-04", "BOOLEAN OPERATORS iff maps to <-> or equals", {"source": "salt_help"}),
            Chunk("salthelp-06", "EXTENDED until weak boundary semantics W", {"source": "salt_help"}),
            Chunk("saltmanual-01", "verbose pdf prose about temporal logic in general", {"source": "salt_manual_pdf"}),
            Chunk("saltmanual-02", "more verbose pdf bibliography references chapter", {"source": "salt_manual_pdf"}),
        ]
        # dense vectors: make the PDF chunks nearest to the query, cards far —
        # so pure dense would rank PDF noise first; BM25 must rescue the card.
        vecs = np.array([[0.0, 1.0], [0.1, 0.9], [1.0, 0.0], [0.99, 0.01]], dtype=np.float32)
        return VectorStore(vecs, chunks, {"version": 1})

    def test_bm25_rescues_card_dense_ranks_low(self):
        store = self._store()
        # query embeds near the PDF chunks (dense favors them); terms name 'iff'
        hits = store.hybrid_search([1.0, 0.0], ["iff", "biconditional"], k=2,
                                   sources=("salt_help", "salt_manual_pdf"))
        ids = [h.chunk.id for h in hits]
        assert "salthelp-04" in ids  # BM25 on 'iff' pulls the boolean card into top-2

    def test_sources_filter_excludes_pdf(self):
        store = self._store()
        hits = store.hybrid_search([1.0, 0.0], ["until"], k=4, sources=("salt_help",))
        assert all(h.chunk.metadata["source"] == "salt_help" for h in hits)

    def test_empty_terms_falls_back_to_dense_order(self):
        store = self._store()
        hits = store.hybrid_search([0.0, 1.0], [], k=2, sources=("salt_help", "salt_manual_pdf"))
        assert len(hits) == 2  # no crash, returns k results
