"""RAG lifecycle: build-if-stale, load, and the `init-rag` CLI entry point.

An index is rebuilt when missing, when the corpus content hash changed, or
when the embedding model changed (all recorded in meta.json). With
PENDULUM_RAG_AUTOBUILD=false a stale/missing index raises instead — for
environments where a surprise multi-minute build would be unwelcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from pendulum.config import PendulumConfig
from pendulum.logging_setup import RunLogger
from pendulum.rag.build_dwyer import load_dwyer_chunks
from pendulum.rag.build_salt import build_salt_chunks
from pendulum.rag.embedder import OllamaEmbedder
from pendulum.rag.store import Chunk, RagError, VectorStore


@dataclass
class RagStores:
    dwyer: VectorStore
    salt: VectorStore


async def ensure_rag_dbs(
    config: PendulumConfig,
    embedder: OllamaEmbedder,
    logger: RunLogger,
    *,
    force: bool = False,
) -> RagStores:
    """Load both indexes, (re)building as needed. Raises RagError when a
    build is needed but autobuild is disabled and force is False."""
    dwyer = await _ensure_one(config, embedder, logger, "dwyer", _dwyer_corpus, force=force)
    salt = await _ensure_one(config, embedder, logger, "salt", _salt_corpus, force=force)
    return RagStores(dwyer=dwyer, salt=salt)


def _dwyer_corpus(logger: RunLogger) -> tuple[list[Chunk], str]:
    chunks, digest = load_dwyer_chunks()
    logger.info("rag", "dwyer_corpus_loaded", chunks=len(chunks))
    return chunks, digest


def _salt_corpus(logger: RunLogger) -> tuple[list[Chunk], str]:
    chunks, digest, dropped = build_salt_chunks()
    # No silent caps: say exactly what was excluded and why.
    logger.info("rag", "salt_corpus_loaded", chunks=len(chunks), dropped_timed_chunks=dropped)
    return chunks, digest


async def _ensure_one(
    config: PendulumConfig,
    embedder: OllamaEmbedder,
    logger: RunLogger,
    name: str,
    corpus_fn: Callable[[RunLogger], tuple[list[Chunk], str]],
    *,
    force: bool,
) -> VectorStore:
    directory = config.rag_dir / name
    chunks, digest = corpus_fn(logger)

    if not force and VectorStore.is_current(directory, embed_model=embedder.model, corpus_hash_=digest):
        store = VectorStore.load(directory)
        logger.debug("rag", "index_loaded", name=name, chunks=len(store))
        return store

    if not force and not config.rag_autobuild:
        raise RagError(
            f"RAG index '{name}' is missing or stale and PENDULUM_RAG_AUTOBUILD=false "
            f"— run `python -m pendulum init-rag`"
        )

    logger.info("rag", "index_building", name=name, chunks=len(chunks), embed_model=embedder.model)
    embeddings = await embedder.embed([c.text for c in chunks])
    store = VectorStore.build(chunks, embeddings, embed_model=embedder.model, corpus_hash_=digest)
    store.save(directory)
    logger.info("rag", "index_built", name=name, dir=str(directory))
    return store
