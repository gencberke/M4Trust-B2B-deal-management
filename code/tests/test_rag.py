from backend.app.config import Settings
from backend.app.services.rag import Chunk, FakeRetriever, Retriever


class FakeModel:
    """model.encode(...) çağrısını kaydeden basit fake — numpy içermez."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]):
        self.calls.append(texts)
        return {"dense_vecs": [[0.1, 0.2, 0.3]]}


class FakeCollection:
    """collection.query(...) çağrısını kaydeden ve canned sonuç döndüren fake."""

    def __init__(self, result: dict):
        self._result = result
        self.calls: list[dict] = []

    def query(self, *, query_embeddings, n_results):
        self.calls.append({"query_embeddings": query_embeddings, "n_results": n_results})
        return self._result


class FakeClient:
    """client.get_collection(name) çağrısını kaydeden ve tek bir collection döndüren fake."""

    def __init__(self, collection: FakeCollection):
        self._collection = collection
        self.requested_names: list[str] = []

    def get_collection(self, name: str):
        self.requested_names.append(name)
        return self._collection


CANNED_RESULT = {
    "documents": [["teslimat 30 gün içinde yapılır.", "cayma hakkı 14 gündür."]],
    "metadatas": [
        [
            {"source": "tbk.pdf", "strategy": "madde", "madde_no": "112", "heading": "İfa"},
            {"source": "kvkk.pdf", "strategy": "paragraf"},
        ]
    ],
    "distances": [[0.12, 0.34]],
}


def _make_retriever():
    settings = Settings()
    model = FakeModel()
    collection = FakeCollection(CANNED_RESULT)
    client = FakeClient(collection)
    retriever = Retriever(settings, client=client, model=model)
    return retriever, model, collection, client


def test_retrieve_calls_model_encode_with_query_list():
    retriever, model, _, _ = _make_retriever()
    retriever.retrieve("teslimat", "legal_articles", k=3)
    assert model.calls == [["teslimat"]]


def test_retrieve_calls_collection_query_with_n_results():
    retriever, _, collection, _ = _make_retriever()
    retriever.retrieve("teslimat", "legal_articles", k=3)
    assert collection.calls[0]["n_results"] == 3
    assert collection.calls[0]["query_embeddings"] == [[0.1, 0.2, 0.3]]


def test_retrieve_maps_chroma_result_to_chunks():
    retriever, _, _, _ = _make_retriever()
    chunks = retriever.retrieve("teslimat", "legal_articles", k=3)
    assert chunks == [
        Chunk(
            text="teslimat 30 gün içinde yapılır.",
            source="tbk.pdf",
            strategy="madde",
            madde_no="112",
            heading="İfa",
            score=0.12,
        ),
        Chunk(
            text="cayma hakkı 14 gündür.",
            source="kvkk.pdf",
            strategy="paragraf",
            madde_no=None,
            heading=None,
            score=0.34,
        ),
    ]


def test_retrieve_missing_madde_no_and_heading_are_none():
    retriever, _, _, _ = _make_retriever()
    chunks = retriever.retrieve("cayma", "legal_articles", k=3)
    second = chunks[1]
    assert second.madde_no is None
    assert second.heading is None


def test_retrieve_defaults_collection_to_legal_articles():
    retriever, _, _, client = _make_retriever()
    retriever.retrieve("teslimat")
    assert client.requested_names == ["legal_articles"]


def test_fake_retriever_returns_fixed_chunks():
    fixed = [
        Chunk(
            text="örnek",
            source="src.pdf",
            strategy="madde",
            madde_no=None,
            heading=None,
            score=0.5,
        )
    ]
    fake = FakeRetriever(fixed)
    assert fake.retrieve("herhangi bir sorgu") == fixed
    assert fake.retrieve("başka bir sorgu", "contract_examples", k=10) == fixed
