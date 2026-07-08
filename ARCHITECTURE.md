# M4Trust — Mimari Referans

> **Amaç:** Geliştirme boyunca sabit kalacak teknik çerçeve — genel mimari, model/servis iletişimi, API contract'ları, tech stack ve tasarım kalıpları. Bu dokümanın dışına çıkan tasarım değişikliği ekip mutabakatı gerektirir.
>
> Sözel bağlam ve gerekçeler: `report/` · 
> Öneriler ve yol haritaları: `plans/`
>
> Bu doküman canlıdır: bir plan uygulandığında **doc-sync protokolü** (bkz. AGENTS.md) ile güncel tutulur — kodu değiştiren iş, eskittiği bölümü de günceller.

## 1. Genel mimari

Tek FastAPI servisi + React SPA + SQLite. Modüller aynı serviste yaşar, sınırlar interface'lerle çizilir. Ana veri akışı:

```
Sözleşme (PDF/DOCX/görsel)
  → DocumentExtractor (markdown'a çevir)
  → privacy (veri sınıflandırma + maskeleme)
  → RAG (mevzuat bağlamı getir)
  → ExtractionService (LLM → yapılandırılmış kural JSON'u)
  → Validator (deterministik: PASS / NEEDS_REVIEW / REJECT)
  → Çift taraflı onay (token'lı taraf linkleri)
  → PaymentProvider.create_pool_payment (para havuzda bekler)
  → Teslimat kanıtları (e-irsaliye birincil, video analizi ikincil)
  → Decision engine → capture / partial / hold / dispute
  → PaymentProvider aksiyonu + evidence bundle
```

```
code/
├── scripts/          # offline hazırlık: dönüşüm, chunk'lama, embedding
├── backend/app/
│   ├── main.py · config.py · db.py · eventbus.py
│   ├── schemas/      # extraction.py (ikili sözleşme) · events.py · api.py
│   ├── routers/      # transactions · approvals · delivery · evidence
│   └── services/
│       ├── documents/         # DocumentExtractor: pdf_digital · docx · ocr · normalizer
│       ├── rag.py             # Chroma retrieval (BGE-M3 lazy singleton)
│       ├── privacy.py         # maskeleme — dış LLM'e giden içeriği sınırlar
│       ├── extraction.py      # ExtractionService: LLMClient + FakeExtractionService
│       ├── validator.py       # deterministik kural kapısı
│       ├── video.py           # VideoAnalyzer: detector + FakeVideoAnalyzer
│       ├── decision.py        # decision engine — saf fonksiyon, I/O yok
│       ├── payment_provider.py# PaymentProvider: MockMokaProvider + RealMokaProvider(v1)
│       └── evidence.py        # zaman damgalı JSON bundle
└── frontend/src/     # api/ · pages/ (Dashboard · TransactionDetail · PartyReview) · components/
```

Frontend route'ları: `/` (dashboard + upload) · `/t/:id` (işlem detayı, demo aksiyonları) · `/t/:id/party?token=…` (taraf görünümü: diff + kural özeti + onay).

## 2. Tech stack

| Katman | Karar |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLite (arka plan işleri: `BackgroundTasks`, queue altyapısı yok) |
| Frontend | React · Vite · Tailwind |
| Doküman | PyMuPDF/PyMuPDF4LLM (dijital PDF) · python-docx/mammoth (DOCX) · Tesseract (OCR) |
| RAG | BAAI/bge-m3 + ChromaDB — koleksiyon `legal_articles`, `code/data/processed/embeddings/chroma/` |
| LLM | "5.4 mini" API — structured output (JSON schema) zorunlu |
| Video | OpenCV frame sampling + hafif detector |
| Ödeme | Moka United havuz ödeme contract'ı (mock'lanır, bkz. §3.3) |

## 3. Model ve dış servis iletişimi

Kural: **tüm dış bağımlılıklar adapter interface arkasındadır ve her birinin Fake/Mock implementasyonu vardır.** Seçim env ile yapılır; uygulama akışı hangi implementasyonun çalıştığını bilmez.

### 3.1 LLM — `ExtractionService`

```python
LLMClient.extract(contract_markdown: str, rag_context: list[Chunk]) -> ExtractionJSON
```

- Girdi **maskelenmiş** markdown + RAG chunk'larıdır; ham dosya asla dış API'ye gitmez.
- Çıktı §4.2'deki şemaya zorlanır (structured output). Şemaya uymayan cevap retry edilir, yine uymazsa NEEDS_REVIEW.
- LLM çıktısı validator'dan geçmeden DB'ye aktif kural olarak yazılmaz. Provider tek dosyada izole — model değişimi diğer kodu etkilemez.

### 3.2 RAG — Chroma + BGE-M3

- Korpus BGE-M3 ile embed'lidir; **sorgu da BGE-M3 ile encode edilmek zorundadır.** Model lazy singleton (ilk istekte yüklenir, süreçte kalır, CPU/`use_fp16=False`).
- RAG yalnızca retrieval yapar; hukuki yorum ve karar üretmez.

### 3.3 Ödeme — `PaymentProvider` (Moka havuz ödeme contract'ı)

```python
PaymentProvider
  .create_pool_payment(...)       # Moka: ödeme oluşturma, IsPoolPayment=1
  .get_payment_status(...)        # Moka: ödeme/transaction listesi
  .approve_pool_payment(...)      # Moka: /PaymentDealer/DoApprovePoolPayment
  .undo_approve_pool_payment(...) # Moka: /PaymentDealer/UndoApprovePoolPayment
  .refund_payment(...)
```

- `PAYMENT_PROVIDER=mock|moka` (demo'da `mock`). `MockMokaProvider` cevapları **gerçek Moka response şeklindedir** (`ResultCode: "Success"`, `Data.IsSuccessful`, `VirtualPosOrderId`); bizim `transaction_id` Moka'ya `OtherTrxCode` olarak taşınır. Böylece v1'de gerçek entegrasyon yalnızca adapter altını değiştirir.
- Release çağrısı yalnızca şu koşulda yapılır: `buyer_approved ∧ seller_approved ∧ decision==RELEASE ∧ state==FUNDS_HELD`. Ayrıntı ve gerekçe: `plans/v1/v1_moka_cüzdan_entegrasyonu.md`.

### 3.4 Video — `VideoAnalyzer`

`analyze(video_path) -> {counts, damage_signals, confidence}` → `delivery_video_analyzed` event'i. Video tek başına ödeme kararı veremez; ikincil risk sinyalidir.

### 3.5 Dış LLM'e giden içeriğin sınırlandırılması

`privacy.py`, markdown dönüşümünden sonra kişisel/hassas alanları (TCKN/vergi no, IBAN, telefon, adres…) tespit edip maskeler; maskeleme haritası lokalde kalır. Regülatif dayanak: TCMB Tebliğ md.9/21, Yönetmelik md.21(7)/62 (bkz. `plans/v1/v1_regulasyon_rag_genisletmesi.md`).

## 4. API contract

### 4.1 REST endpoint'leri

| Endpoint | İş |
|---|---|
| `POST /api/transactions` | Sözleşme upload → pipeline başlar → `{id, buyer_link, seller_link}` |
| `GET /api/transactions` | İşlem listesi |
| `GET /api/transactions/{id}` | Detay: extraction, validator raporu, event timeline, ödeme durumu |
| `GET /api/transactions/{id}/party-view?token=…` | Taraf perspektifi (token → party çözümü) |
| `POST /api/transactions/{id}/approvals` | Body `{token}` — token sahibi tarafın onayı; yanlış token → 403 |
| `POST /api/transactions/{id}/events/e-irsaliye` | E-irsaliye simülasyonu (demo butonu) |
| `POST /api/transactions/{id}/delivery-video` | Video upload → arka planda analiz |
| `GET /api/transactions/{id}/evidence` | Kanıt paketi (JSON bundle) |

### 4.2 Extraction JSON şeması — **ikili sözleşme noktası**

`schemas/extraction.py` (Pydantic) tek doğruluk kaynağıdır; fake ve gerçek extraction aynı şemayı döndürür. Değişiklik ekip mutabakatı gerektirir.

```json
{
  "contract_id": "string",
  "parties": {
    "buyer":  {"name": "string", "tax_id": "string|null"},
    "seller": {"name": "string", "tax_id": "string|null"}
  },
  "commercial_terms": {
    "currency": "TRY|USD|EUR|OTHER",
    "total_amount": 0,
    "goods": [{"name": "string", "quantity": 0, "unit": "string"}],
    "delivery_deadline": "YYYY-MM-DD|null"
  },
  "payment_rules": [
    {
      "milestone": "string",
      "trigger": "approval|e_invoice|delivery_video|manual_review",
      "percentage": 0,
      "required_evidence": ["contract", "e_irsaliye", "video"],
      "source_quote": "string",
      "confidence": 0.0
    }
  ],
  "risk_flags": ["string"],
  "needs_manual_review": false
}
```

### 4.3 İç event zarfı

Tüm modüller `eventbus.emit()` ile konuşur; her event `events` tablosuna yazılır (evidence bundle buradan derlenir). Zarf: `transaction_id · event_type · payload · source · created_at`.

Event tipleri: `contract_extracted` · `rules_validated` · `buyer_approved` · `seller_approved` · `e_irsaliye_received` · `delivery_video_analyzed` · `payment_decision_created` · `mock_payment_executed` · `dispute_opened`

## 5. Veri modeli ve state machine

Tablolar: `transactions` (state, buyer_token, seller_token, markdown) · `extracted_rules` (extraction_json, validator_status, validator_report) · `approvals` · `events` · `mock_payments` · `evidence`

```
uploaded → extracting → awaiting_review → awaiting_approval
        → active (pool/funds_held) → evidence_pending
        → decided (captured | partially_captured | disputed | held)

validator REJECT → rejected (akış durur)
```

Karar → ödeme aksiyonu: tam teslim `capture` · kısmi `partial_capture` · beklemede pre-auth devam · çelişkili kanıt `mark_dispute` (capture gitmez, evidence snapshot alınır).

## 6. Dışına çıkılmayacak tasarım kalıpları

1. **LLM para yolunda değildir.** LLM önerir → validator (deterministik) denetler → insanlar onaylar → motor uygular. Release endpoint'ini yalnızca deterministik motor çağırır.
2. **Validator kapısı atlanamaz.** LLM çıktısı PASS almadan aktif kural olmaz; NEEDS_REVIEW insan ister; REJECT akışı durdurur. UI her zaman gerekçeyi gösterir.
3. **Her dış bağımlılık adapter + fake çifti olarak yazılır** ve env ile seçilir (LLM, ödeme, video). Fake'ler demo fallback'idir.
4. **Event bus = events tablosu.** Ayrı mesajlaşma altyapısı kurulmaz; kanıt zinciri bu tablodan üretilir.
5. **Decision engine saf fonksiyondur** — I/O yapmaz, girdi/çıktısı test edilebilir.
6. **Taraf kimliği = token.** Auth/users tablosu yok; capability URL modeli.
7. **Local-first.** Runtime'daki tek dış çağrı LLM API'sidir; o da yalnızca maskelenmiş içerik alır.
8. **Gerçek para hareketi ve gerçek kart verisi yoktur** (demo). Prod anlatısı: lisanslı altyapının (Moka havuz/cüzdan) üstünde karar-kanıt katmanı.
