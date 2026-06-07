"""Generic vector retriever (ADR-0005): embed a query, search a vector store, return cited items.

Works with any ``ModelProvider`` (for query embeddings) + ``VectorRepository``, so it is provider/
store-agnostic and testable with fakes. Chunk text + source are read from the vector metadata that
ingestion stored.
"""

from __future__ import annotations

from collections.abc import Sequence

from personalai_contracts.ports import (
    Citation,
    ModelProvider,
    RetrievalQuery,
    RetrievedItem,
    VectorRepository,
)


class VectorRetriever:
    """A :class:`Retriever` that embeds the query and searches a vector store."""

    name = "vector"

    def __init__(
        self, provider: ModelProvider, vectors: VectorRepository, embed_model: str
    ) -> None:
        self._provider = provider
        self._vectors = vectors
        self._embed_model = embed_model

    async def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedItem]:
        embeddings = await self._provider.embed([query.text], self._embed_model)
        if not embeddings.vectors:
            return []
        matches = await self._vectors.query(embeddings.vectors[0], query.top_k)
        items: list[RetrievedItem] = []
        for match in matches:
            metadata = dict(match.metadata)
            chunk_index = metadata.get("chunk_index")
            items.append(
                RetrievedItem(
                    content=str(metadata.get("text", "")),
                    score=match.score,
                    citation=Citation(
                        source_id=str(metadata.get("document_id", "")),
                        locator=None if chunk_index is None else f"chunk {chunk_index}",
                    ),
                    metadata=metadata,
                )
            )
        return items
