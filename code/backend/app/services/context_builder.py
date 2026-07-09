"""ContextBuilder — RAG retrieval orkestrasyonu (mevcut Retriever'ı sarmalar).

Mevcut `Retriever` (rag.py) tek query / tek koleksiyon düşük seviye araçtır.
ContextBuilder bunun üstüne oturur: çoklu query planlama (sabit temel + sinyal-
tetiklemeli), çoklu koleksiyon retrieval (legal_articles + contract_examples +
koşullu security_controls), dedupe/kota/karakter-limiti ve LLM için kaynak-tipli
tek metin (`formatted_for_llm`) üretir.

Kritik semantik: `Chunk.score` Chroma **distance**'ıdır (rag.py) — DÜŞÜK değer
daha iyi. `ContextSource.score` aynı semantiği taşır; kota içinde en düşük
distance'lılar seçilir, karakter limiti aşımında en YÜKSEK distance'lılar
düşürülür. Sıralama ters çevrilmez.

Retriever DEĞİŞMEZ; yalnızca kullanılır. Retriever kurulamaz/hata verirse
(ör. ağır bağımlılıklar eksik ya da koleksiyon henüz build edilmemiş) ilgili
query sessizce atlanır — hat bağlamsız/kısmi bağlamla graceful devam eder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.app.config import Settings
from backend.app.services.rag import Chunk

SourceType = Literal["legal", "contract_example", "security"]

# ContextBuilder'ın koşullu security retrieval'ı bu tiplerden biri
# `privacy_report.detected_types` içinde geçtiğinde tetiklenir (Faz 4 privacy
# bu tipleri üretir; Faz 1'de yalnızca metin sinyali yolu aktif olabilir).
_CARD_DATA_TYPES = frozenset({"PAN", "CVV", "TRACK_DATA", "PIN"})

# Kaynak-tipi kotaları ve toplam karakter limiti (packing'in basit hali).
_QUOTA: dict[SourceType, int] = {"legal": 6, "contract_example": 2, "security": 2}
_CHAR_LIMIT = 12_000

# contract_examples query'si için maskelenmiş metnin ilk N karakteri (mevcut
# CLI davranışıyla aynı).
_CONTRACT_QUERY_CHAR_LIMIT = 1000

# Sabit temel legal query'ler (her sözleşme için sorulur).
_BASE_LEGAL_QUERIES: list[tuple[str, str]] = [
    ("ödeme şartları ödeme hizmeti fon aktarımı taraf yükümlülükleri", "payment_terms"),
    ("teslimat mal teslimi hizmet ifası kabul ayıplı mal", "delivery"),
    ("gecikme temerrüt cezai şart iade fesih", "default_penalty"),
]

# (metinde geçen sinyal anahtar kelimeleri) -> ek legal query metni + purpose.
_SIGNAL_LEGAL_QUERIES: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("kişisel veri", "müşteri bilgisi", "hassas veri", "kvkk"),
        "kişisel veri işleme hassas müşteri verisi veri paylaşımı",
        "personal_data",
    ),
    (
        ("dış hizmet", "bulut", "api", "yurt dışı"),
        "dış hizmet alımı yurt dışı veri aktarımı veri lokalizasyonu",
        "outsourcing",
    ),
]

# Metinde bunlardan biri geçerse (veya privacy_report kart-verisi tipi
# içerirse) security_controls koleksiyonuna gidilir.
_CARD_SIGNAL_KEYWORDS: tuple[str, ...] = ("kart", "pan", "cvv", "cvc", "cardholder", "pos")

# Kart/güvenlik sinyalinde sorulan security query'leri.
_SECURITY_QUERIES: list[tuple[str, str]] = [
    ("kart verisi saklama maskeleme PAN CVV hassas doğrulama verisi", "card_storage"),
    ("kart sahibi verisi iletim güçlü kriptografi ödeme sağlayıcı", "card_transmission"),
]

_LABELS: dict[SourceType, str] = {
    "legal": "LEGAL_SOURCE",
    "contract_example": "CONTRACT_EXAMPLE",
    "security": "SECURITY_CONTROL",
}


@dataclass(frozen=True)
class RetrievalQuery:
    """Planlanan tek bir retrieval sorgusu."""

    text: str
    purpose: str
    collection: str
    k: int


@dataclass(frozen=True)
class ContextSource:
    """LLM'e verilecek tek bir kaynak (retrieve edilmiş Chunk'ın zenginleştirilmiş hali).

    `score` Chroma distance'ıdır — DÜŞÜK daha iyi (Chunk.score ile aynı semantik).
    """

    source_type: SourceType
    source: str
    text: str
    score: float
    collection: str
    madde_no: str | None = None
    heading: str | None = None


@dataclass(frozen=True)
class ContextPack:
    """ContextBuilder.build() çıktısı — planlanan query'ler + seçilen kaynaklar + LLM metni."""

    queries: list[RetrievalQuery] = field(default_factory=list)
    sources: list[ContextSource] = field(default_factory=list)
    formatted_for_llm: str = ""
    risk_flags: list[str] = field(default_factory=list)


class ContextBuilder:
    """Retriever'ı sarmalayıp çoklu-query/çoklu-koleksiyon bağlam paketi üretir."""

    def __init__(self, settings: Settings, retriever):
        self._settings = settings
        self._retriever = retriever
        self._security_collection = getattr(
            settings, "security_collection", "security_controls"
        )
        self._collection_type: dict[str, SourceType] = {
            settings.legal_collection: "legal",
            settings.contract_collection: "contract_example",
            self._security_collection: "security",
        }

    def build(self, masked_markdown: str, privacy_report=None) -> ContextPack:
        """Maskelenmiş markdown'dan (ve varsa privacy_report'tan) bir ContextPack üretir.

        Retriever hata verirse (deps eksik / koleksiyon yok) ilgili query atlanır;
        hiç kaynak gelmezse boş `formatted_for_llm` ile bağlamsız devam edilir.
        """
        queries = self._plan_queries(masked_markdown, privacy_report)

        collected: list[ContextSource] = []
        for query in queries:
            try:
                chunks = self._retriever.retrieve(
                    query.text, collection=query.collection, k=query.k
                )
            except Exception:
                # Graceful degradation: ör. security_controls henüz build
                # edilmemiş ya da chromadb/FlagEmbedding kurulu değil.
                continue
            source_type = self._collection_type.get(query.collection, "legal")
            for chunk in chunks:
                collected.append(self._to_source(chunk, source_type, query.collection))

        selected = self._apply_quota_and_limit(self._dedupe(collected))
        risk_flags = list(getattr(privacy_report, "risk_flags", []) or [])
        return ContextPack(
            queries=queries,
            sources=selected,
            formatted_for_llm=self._format_for_llm(selected),
            risk_flags=risk_flags,
        )

    def pack_from_chunks(self, chunks: list[Chunk], collection: str) -> ContextPack:
        """Tek koleksiyondan gelen ham Chunk'ları pack'e sarar (deprecated --collection debug yolu).

        Query planlama yapmaz; verilen chunk'ları aynı dedupe/kota/limit/format
        hattından geçirir — böylece tek bir formatlama yolu korunur.
        """
        source_type = self._collection_type.get(collection, "legal")
        sources = [self._to_source(ch, source_type, collection) for ch in chunks]
        selected = self._apply_quota_and_limit(self._dedupe(sources))
        return ContextPack(
            queries=[
                RetrievalQuery(
                    text="(deprecated --collection debug)", purpose="debug", collection=collection, k=len(chunks)
                )
            ],
            sources=selected,
            formatted_for_llm=self._format_for_llm(selected),
            risk_flags=[],
        )

    # --- query planlama -----------------------------------------------------

    def _plan_queries(self, masked_markdown: str, privacy_report) -> list[RetrievalQuery]:
        lowered = masked_markdown.lower()
        queries: list[RetrievalQuery] = []

        for text, purpose in _BASE_LEGAL_QUERIES:
            queries.append(
                RetrievalQuery(text=text, purpose=purpose, collection=self._settings.legal_collection, k=3)
            )

        for keywords, text, purpose in _SIGNAL_LEGAL_QUERIES:
            if any(kw in lowered for kw in keywords):
                queries.append(
                    RetrievalQuery(text=text, purpose=purpose, collection=self._settings.legal_collection, k=3)
                )

        contract_query = masked_markdown[:_CONTRACT_QUERY_CHAR_LIMIT]
        queries.append(
            RetrievalQuery(
                text=contract_query,
                purpose="contract_structure",
                collection=self._settings.contract_collection,
                k=2,
            )
        )

        if self._has_card_signal(lowered, privacy_report):
            for text, purpose in _SECURITY_QUERIES:
                queries.append(
                    RetrievalQuery(text=text, purpose=purpose, collection=self._security_collection, k=2)
                )

        return queries

    @staticmethod
    def _has_card_signal(lowered_text: str, privacy_report) -> bool:
        detected = getattr(privacy_report, "detected_types", None)
        if detected and _CARD_DATA_TYPES & set(detected):
            return True
        return any(kw in lowered_text for kw in _CARD_SIGNAL_KEYWORDS)

    # --- dönüşüm / dedupe / kota --------------------------------------------

    def _to_source(self, chunk: Chunk, source_type: SourceType, collection: str) -> ContextSource:
        return ContextSource(
            source_type=source_type,
            source=chunk.source,
            text=chunk.text,
            score=chunk.score,
            collection=collection,
            madde_no=chunk.madde_no,
            heading=chunk.heading,
        )

    @staticmethod
    def _dedupe(sources: list[ContextSource]) -> list[ContextSource]:
        """Aynı text ya da aynı (source, madde_no) tekrarlarını atar; en düşük distance kalır."""
        ordered = sorted(sources, key=lambda s: s.score)  # en iyi (düşük distance) önce
        seen_text: set[int] = set()
        seen_madde: set[tuple[str, str]] = set()
        out: list[ContextSource] = []
        for src in ordered:
            text_key = hash(src.text)
            madde_key = (src.source, src.madde_no) if src.madde_no is not None else None
            if text_key in seen_text:
                continue
            if madde_key is not None and madde_key in seen_madde:
                continue
            seen_text.add(text_key)
            if madde_key is not None:
                seen_madde.add(madde_key)
            out.append(src)
        return out

    def _apply_quota_and_limit(self, sources: list[ContextSource]) -> list[ContextSource]:
        """Kaynak-tipi kotasını ve toplam karakter limitini uygular.

        `sources` distance'a göre artan sıralıdır (dedupe böyle döner). Kota
        best-first uygulanır; karakter limiti aşılırsa en alakasız (en yüksek
        distance) kaynaklar sondan düşürülür.
        """
        counts: dict[SourceType, int] = {}
        kept: list[ContextSource] = []
        for src in sources:
            used = counts.get(src.source_type, 0)
            if used >= _QUOTA.get(src.source_type, 0):
                continue
            counts[src.source_type] = used + 1
            kept.append(src)

        while kept and len(self._format_for_llm(kept)) > _CHAR_LIMIT:
            kept.pop()  # sondaki = en yüksek distance = en alakasız
        return kept

    # --- LLM formatı --------------------------------------------------------

    @staticmethod
    def _format_for_llm(sources: list[ContextSource]) -> str:
        if not sources:
            return ""
        counters: dict[SourceType, int] = {}
        blocks: list[str] = []
        for src in sources:
            counters[src.source_type] = counters.get(src.source_type, 0) + 1
            label = f"{_LABELS[src.source_type]}_{counters[src.source_type]}"
            locator = src.madde_no or src.heading or "-"
            header = (
                f"[{label}] collection: {src.collection} | source: {src.source} | "
                f"konum: {locator} | score: {src.score:.4f}"
            )
            blocks.append(f"{header}\n{src.text}")
        return "\n\n".join(blocks)
