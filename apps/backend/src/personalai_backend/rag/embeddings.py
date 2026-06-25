"""A ``langchain_core`` ``Embeddings`` over our ``ModelProvider`` seam (ADR-0012, #420).

Embeddings MUST stay on PersonalAI's ``ModelProvider.embed`` seam so embed calls keep flowing
through our provider (loopback Ollama, egress guard) -- we deliberately do NOT use
``langchain-ollama`` (CISO review #420). This is a tiny ``Embeddings`` subclass that forwards to
``provider.embed(texts, model)`` and unpacks the ``EmbeddingResult``.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from personalai_contracts.ports import ModelProvider

# A retrieval query is a question, not a document. Cap its length before embedding so a query
# polluted with folded attachment text (#416/#431) cannot exceed the embedding model's input limit
# and EOF the embed runner. Mirrors core.retrieval.VectorRetriever._MAX_QUERY_CHARS.
_MAX_QUERY_CHARS = 2000


class ProviderEmbeddings(Embeddings):
    """Adapt a PersonalAI :class:`ModelProvider` to the ``langchain_core`` ``Embeddings`` API.

    The async methods are the real path (the retriever runs in an async context); the sync methods
    required by the base class are not used by our retriever and raise to prevent an accidental
    blocking call from a sync LangChain code path.
    """

    def __init__(self, provider: ModelProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = await self._provider.embed(texts, self._model)
        return [[float(v) for v in vec] for vec in result.vectors]

    async def aembed_query(self, text: str) -> list[float]:
        capped = text[:_MAX_QUERY_CHARS]
        result = await self._provider.embed([capped], self._model)
        if not result.vectors:
            return []
        return [float(v) for v in result.vectors[0]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError(
            "ProviderEmbeddings is async-only; use aembed_documents (our retrieval path is async)"
        )

    def embed_query(self, text: str) -> list[float]:  # pragma: no cover
        raise NotImplementedError(
            "ProviderEmbeddings is async-only; use aembed_query (our retrieval path is async)"
        )
