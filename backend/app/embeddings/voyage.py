"""Optional hosted embeddings (Voyage AI) over plain HTTP.

The database column is VECTOR(384), so only a Voyage model/dimension combination that returns 384 numbers
can be used without a new migration. If the dimension differs, this class refuses to start instead of
silently corrupting the index.
"""

from __future__ import annotations

import httpx

from app.config import EMBEDDING_DIM

_URL = "https://api.voyageai.com/v1/embeddings"


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise RuntimeError("VOYAGE_API_KEY is required when EMBEDDING_PROVIDER=voyage")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self.dim = EMBEDDING_DIM

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        payload = {"input": texts, "model": self._model, "input_type": input_type, "output_dimension": self.dim}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(_URL, json=payload, headers=self._headers)
            response.raise_for_status()
        vectors: list[list[float]] = [row["embedding"] for row in response.json()["data"]]
        if vectors and len(vectors[0]) != self.dim:
            raise RuntimeError(
                f"{self._model} returned {len(vectors[0])} dimensions but the database expects {self.dim}. "
                "Changing the dimension needs a new migration and a full reindex."
            )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), 64):
            out += await self._embed(texts[start : start + 64], "document")
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "query"))[0]
