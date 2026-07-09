"""ContextBuilder testleri — query planlama, çoklu retrieval, dedupe/kota/limit.

Fake retriever ile ağır RAG bağımlılıkları olmadan bağımsız çalışır. Chroma
`score` = distance semantiği (DÜŞÜK daha iyi) burada da korunur.
"""

from __future__ import annotations

from backend.app.config import Settings
from backend.app.services.context_builder import (
    ContextBuilder,
    ContextPack,
    ContextSource,
)
from backend.app.services.rag import Chunk


class RecordingRetriever:
    """Koleksiyon adına göre sabit Chunk listesi döndüren; çağrıları kaydeden fake."""

    def __init__(self, by_collection: dict[str, list[Chunk]] | None = None):
        self._by_collection = by_collection or {}
        self.calls: list[tuple[str, str, int]] = []  # (query, collection, k)

    def retrieve(self, query: str, collection: str | None = None, k: int = 5) -> list[Chunk]:
        self.calls.append((query, collection, k))
        return list(self._by_collection.get(collection, []))


class BrokenRetriever:
    """Her çağrıda ImportError fırlatan retriever (ağır deps eksikmiş gibi)."""

    def __init__(self):
        self.calls: list[tuple[str, str, int]] = []

    def retrieve(self, query: str, collection: str | None = None, k: int = 5) -> list[Chunk]:
        self.calls.append((query, collection, k))
        raise ImportError("chromadb/FlagEmbedding yüklü değil")


def _chunk(text: str, *, source: str = "6098kk", madde_no: str | None = None, score: float = 0.5) -> Chunk:
    return Chunk(text=text, source=source, strategy="madde", madde_no=madde_no, heading=None, score=score)


def _settings() -> Settings:
    return Settings()


def _collections_of(calls) -> list[str]:
    return [c[1] for c in calls]


def test_base_queries_hit_legal_and_contract_without_signal():
    retriever = RecordingRetriever()
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("Sıradan bir ticari sözleşme metni. Teslimat ve ödeme.")

    cols = _collections_of(retriever.calls)
    assert cols.count("legal_articles") == 3  # 3 sabit temel legal query
    assert cols.count("contract_examples") == 1
    assert "security_controls" not in cols  # sinyal yok -> security'ye gidilmez
    assert isinstance(pack, ContextPack)


def test_personal_data_signal_adds_extra_legal_query():
    retriever = RecordingRetriever()
    builder = ContextBuilder(_settings(), retriever)

    builder.build("Taraflar KVKK kapsamında kişisel veri işleyecektir.")

    cols = _collections_of(retriever.calls)
    assert cols.count("legal_articles") == 4  # 3 temel + 1 sinyal


def test_card_signal_triggers_security_collection():
    retriever = RecordingRetriever()
    builder = ContextBuilder(_settings(), retriever)

    builder.build("Ödeme kart (POS) üzerinden alınacaktır. CVV saklanmaz.")

    cols = _collections_of(retriever.calls)
    assert "security_controls" in cols
    assert cols.count("security_controls") == 2  # 2 security query


def test_no_card_signal_never_queries_security():
    retriever = RecordingRetriever()
    builder = ContextBuilder(_settings(), retriever)

    builder.build("Endüstriyel pompa teslimatı ve ödeme planı.")

    assert "security_controls" not in _collections_of(retriever.calls)


def test_privacy_report_detected_type_triggers_security():
    class _Report:
        detected_types = {"PAN"}
        risk_flags = ["CHD_CONTEXT"]

    retriever = RecordingRetriever()
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("Metinde açık kart sinyali yok.", privacy_report=_Report())

    assert "security_controls" in _collections_of(retriever.calls)
    assert pack.risk_flags == ["CHD_CONTEXT"]


def test_dedupe_collapses_same_chunk_from_multiple_queries():
    same = _chunk("MADDE 21 - aynı metin", madde_no="21", score=0.3)
    retriever = RecordingRetriever({"legal_articles": [same, same]})
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("teslimat ödeme")

    texts = [s.text for s in pack.sources if s.source_type == "legal"]
    assert texts.count("MADDE 21 - aynı metin") == 1


def test_legal_quota_capped_at_six():
    chunks = [_chunk(f"MADDE {i} metni", madde_no=str(i), score=0.1 * i) for i in range(1, 11)]
    retriever = RecordingRetriever({"legal_articles": chunks})
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("teslimat ödeme")

    legal = [s for s in pack.sources if s.source_type == "legal"]
    assert len(legal) == 6


def test_quota_keeps_lowest_distance_sources():
    best = _chunk("en iyi", madde_no="1", score=0.05)
    worst = [_chunk(f"kotu {i}", madde_no=str(i + 10), score=0.9) for i in range(10)]
    retriever = RecordingRetriever({"legal_articles": [*worst, best]})
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("teslimat ödeme")

    assert any(s.text == "en iyi" for s in pack.sources)  # en düşük distance elenmiyor


def test_char_limit_drops_highest_distance_first():
    big_best = _chunk("A" * 8000, madde_no="1", score=0.1)
    big_worst = _chunk("B" * 8000, madde_no="2", score=0.8)
    retriever = RecordingRetriever({"legal_articles": [big_best, big_worst]})
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("teslimat ödeme")

    assert len(pack.formatted_for_llm) <= 12_000
    texts = [s.text for s in pack.sources]
    assert ("A" * 8000) in texts  # düşük distance kalır
    assert ("B" * 8000) not in texts  # yüksek distance düşer


def test_formatted_for_llm_labels_and_sources():
    retriever = RecordingRetriever(
        {"legal_articles": [_chunk("MADDE 21 metni", madde_no="21", score=0.2)]}
    )
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("teslimat ödeme")

    assert "[LEGAL_SOURCE_1]" in pack.formatted_for_llm
    assert "source: 6098kk" in pack.formatted_for_llm
    assert "MADDE 21 metni" in pack.formatted_for_llm


def test_broken_retriever_degrades_to_empty_pack():
    retriever = BrokenRetriever()
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("teslimat ödeme kart CVV")  # security dahil tüm query'ler denenir

    assert pack.sources == []
    assert pack.formatted_for_llm == ""
    assert len(retriever.calls) > 0  # denendi ama hepsi hata verdi


def test_missing_security_collection_keeps_legal_context():
    # security koleksiyonu yok -> retrieve orada boş/hatalı; legal/contract kalır.
    retriever = RecordingRetriever(
        {"legal_articles": [_chunk("legal metin", madde_no="1", score=0.2)]}
    )
    builder = ContextBuilder(_settings(), retriever)

    pack = builder.build("kart CVV içeren metin")  # security tetiklenir ama boş döner

    assert any(s.source_type == "legal" for s in pack.sources)
    assert all(s.source_type != "security" for s in pack.sources)
    assert isinstance(pack, ContextPack)
    assert all(isinstance(s, ContextSource) for s in pack.sources)
