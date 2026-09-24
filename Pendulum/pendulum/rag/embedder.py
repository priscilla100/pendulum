"""Embedding provider: Ollama's /api/embed (all-minilm by default), batched."""

from __future__ import annotations

from pendulum.llm.ollama import OllamaClient


class OllamaEmbedder:
    def __init__(self, client: OllamaClient, model: str, batch_size: int = 32):
        self._client = client
        self.model = model
        self._batch_size = max(1, batch_size)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in order; batches to keep request sizes sane."""
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            out.extend(await self._client.embed(batch, model=self.model))
        return out

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]
