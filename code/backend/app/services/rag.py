"""RAG retriever — BGE-M3 ile encode edilen sorguyu Chroma koleksiyonlarında arar.

Ağır bağımlılıklar (`chromadb`, `FlagEmbedding`) yalnızca metot içinde (lazy)
import edilir; bu modül import edildiğinde ne torch ne de chromadb yüklenmesi
gerekmez (§3.2). Client/model test için enjekte edilebilir; verilmezse lazy
singleton olarak oluşturulur.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.config import Settings


@dataclass(frozen=True)
class Chunk:
    """Retrieve edilen tek bir metin parçası ve kaynağı."""

    text: str
    source: str
    strategy: str
    madde_no: str | None
    heading: str | None
    score: float


class Retriever:
    """Sorguyu BGE-M3 ile encode edip Chroma koleksiyonunda arar."""

    def __init__(self, settings: Settings, *, client=None, model=None):
        self._settings = settings
        self._client = client
        self._model = model

    def _get_model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self._settings.rag_model_name, use_fp16=False)
        return self._model

    def _get_client(self):
        if self._client is None:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self._settings.chroma_dir))
        return self._client

    def retrieve(self, query: str, collection: str | None = None, k: int = 5) -> list[Chunk]:
        collection_name = collection if collection is not None else self._settings.legal_collection

        model = self._get_model()
        vec = model.encode([query])["dense_vecs"][0]
        emb = vec.tolist() if hasattr(vec, "tolist") else list(vec)

        client = self._get_client()
        coll = client.get_collection(collection_name)
        result = coll.query(query_embeddings=[emb], n_results=k)

        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]

        chunks: list[Chunk] = []
        for text, meta, distance in zip(documents, metadatas, distances):
            chunks.append(
                Chunk(
                    text=text,
                    source=meta.get("source"),
                    strategy=meta.get("strategy"),
                    madde_no=meta.get("madde_no"),
                    heading=meta.get("heading"),
                    score=distance,
                )
            )
        return chunks


class FakeRetriever:
    """Test/downstream için sabit bir `Chunk` listesi döndüren fake retriever."""

    def __init__(self, chunks: list[Chunk] | None = None):
        self._chunks = chunks if chunks is not None else []

    def retrieve(self, query: str, collection: str | None = None, k: int = 5) -> list[Chunk]:
        return list(self._chunks)
