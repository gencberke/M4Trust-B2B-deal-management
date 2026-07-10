# M4Trust — Sıfır-Context Ajan Handoff Dokümanı

> **Bu doküman kimin için:** Proje hakkında hiçbir bilgisi ve kod tarafında hiçbir context'i olmayan bir ajan/geliştirici. Amaç: bu dokümanı okuyan ajan, başka hiçbir şey okumadan projenin ne olduğunu, neyin nerede olduğunu, neyin bitip neyin eksik olduğunu ve hangi kurallara uyması gerektiğini bilir hale gelir.
> **Güncellik:** 10.07.2026. Son güncelleme: *opsiyonel fiziksel teslimat ve video takip politikası* planının backend uygulaması ([plans/done/opsiyonel_fiziksel_teslimat_ve_video_takip_politikasi.md](../plans/done/opsiyonel_fiziksel_teslimat_ve_video_takip_politikasi.md)). Test durumu: **214 passed / 0 failed**. Önceki sürümde kayıtlı "video counts şekli" kırığı **giderildi** (decision engine artık `unit_count` okur).
> **Öncelik sırası:** Bu doküman anlatıcıdır; bir çelişki durumunda bağlayıcı kaynak her zaman repo kökündeki **ARCHITECTURE.md**'dir, süreç kuralları **AGENTS.md**'dedir.

---

## 1. Proje nedir?

**M4Trust**, Moka United Fintech Hackathon için geliştirilen (süre: 5-6 gün, ekip: 2 kişi) AI destekli bir **B2B şartlı ödeme / güven katmanı**dır. Çözdüğü problem: şirketler arası ticarette "önce mal mı, önce para mı?" güvensizliği — akreditife erişemeyen KOBİ'ler için.

Ürün vaadi tek zincirdir ve tüm mimari bu zinciri korur:

```
Sözleşme yüklenir → AI (LLM) okur ve ödeme kuralları ÖNERİR
→ deterministik VALIDATOR denetler (PASS/NEEDS_REVIEW/REJECT)
→ YÖNETİCİ takip politikasını seçer ve KİLİTLER (off / document_only / document_and_video)
→ iki taraf (alıcı+satıcı) token'lı linklerle ONAYLAR
→ para lisanslı sağlayıcının (Moka) HAVUZUNDA bekletilir (mock)
→ (gerekiyorsa) teslimat kanıtları gelir (e-irsaliye birincil, video ikincil/advisory)
→ SETTLEMENT COORDINATOR deterministik DECISION ENGINE'i çağırır: capture / partial_capture / hold
→ ödeme aksiyonu + indirilebilir kanıt paketi (evidence bundle)
```

**LLM asla ödeme kararı vermez ve para yolunda değildir.** Bu, projenin pazarlama cümlesi değil, kodda guard'larla zorlanan değişmez kuraldır. Aynı şey video için de geçerlidir: **opsiyonel video tek başına miktar, oran, release veya dispute üretemez.**

Fiziksel teslimat ve video artık varsayılan yol değildir: sistem sözleşmeden fiziksel teslimatı yalnızca **önerir**, takibi yönetici açar. Hizmet/danışmanlık/lisans gibi anlaşmalar iki onayla, hiçbir teslimat kanıtı beklemeden ilerler.

Jüri demosunun senaryoları (`code/tests/test_api_flow.py`de uçtan uca test edilir): (A) hizmet/approval-only → capture, (B) fiziksel mal + `document_only` → e-irsaliyeden capture, (C) `document_and_video` uyumlu video → destekleyici bulgu + capture, (D) yüksek güvenli video anomalisi → **hold + manuel inceleme** (release yok, otomatik dispute yok), (E) sözleşmesel video → yönetici kapatamaz/zayıflatamaz (`document_and_video` zorunlu), video gelene kadar hold, (F) **"altın an"**: yüzdeleri 100 etmeyen bozuk sözleşme → validator REJECT + gerekçe.

## 2. Değişmez kurallar (bunları asla delme)

ARCHITECTURE.md §6'nın özeti — koda dokunan her iş bunlara uymak zorunda:

1. **LLM para yolunda değildir.** Release'i yalnızca deterministik akış çağırır.
2. **Validator kapısı atlanamaz.** PASS almadan hiçbir LLM çıktısı aktif kural olmaz; REJECT akışı durdurur; UI her zaman gerekçe gösterir.
3. **Her dış bağımlılık adapter + fake çiftidir**, env ile seçilir (LLM: `LLM_PROVIDER`, ödeme: `PAYMENT_PROVIDER`, video: `VIDEO_PROVIDER`). Fake'ler demo fallback'idir ve her zaman çalışır.
4. **Event bus = `events` tablosu.** Ayrı mesajlaşma altyapısı yok; kanıt zinciri bu tablodan derlenir.
5. **Decision engine ve validator saf fonksiyondur** — I/O yapmaz.
6. **Taraf kimliği = token** (capability URL). Auth/users tablosu yok. Yönetici de bir token'dır (`manager_token`); token'lar log/event/evidence'a girmez.
7. **Local-first:** runtime'daki tek dış çağrı LLM API'sidir ve **yalnızca maskelenmiş içerik** alır. Kart verisi (CVV/track/PIN) tespitinde dış çağrı **hiç yapılmaz**.
8. **Gerçek para hareketi ve gerçek kart verisi yoktur** (demo).
9. **`schemas/extraction.py` (§4.2 şeması) donmuş ikili sözleşmedir** — alan ekleme/çıkarma/yeniden adlandırma ekip mutabakatı gerektirir. Platformun takip tercihi bu şemaya **yazılmaz** (`schemas/tracking.py`de yaşar).
10. **Video advisory'dir.** Opsiyonel video `required_evidence`e girmez, yokluğu bloklamaz, `delivered_quantity` fallback'i değildir; en fazla `hold` + manuel inceleme tetikler.
11. **Takip politikası taraf onaylarından önce kilitlenir.** Kilitsiz onay 409'dur; sözleşmesel kanıt şartı yönetici tercihiyle kapatılamaz **veya zayıflatılamaz** (sözleşmesel video ⇒ `document_and_video` zorunlu).
12. **Release guard tek yerdedir** (`services/settlement.py`); `decision.py` saf kalır.
13. Dokümantasyon ve UI dili **Türkçe**; kod tanımlayıcıları İngilizce.

## 3. Repo haritası

```
M4Trust/
├── ARCHITECTURE.md      ← BAĞLAYICI teknik referans (mimari, contract'lar, §6 değişmezler)
├── AGENTS.md            ← süreç kuralları: plan yaşam döngüsü + doc-sync protokolü + pratik notlar
├── YOL_HARITASI.md      ← hackathon sıralaması + demo senaryoları + video detector araştırması
├── CLAUDE.md            ← ajan giriş noktası (AGENTS.md'yi işaret eder)
├── plans/               ← plan durumu = klasör: planning/ → ready/ → (uygulama) → review/ → done/
├── report/              ← anlatı raporları (bu doküman, dev handoff, kısa rapor; bkz. report/README.md)
├── diagram/             ← 4 akış diyagramı PNG (ana akış/onay, evidence, karar motoru, kanıt kanalları)
└── code/
    ├── requirements.txt ← chromadb, FlagEmbedding, pydantic, openai, pymupdf, python-docx,
    │                      pytesseract, pillow, requests, python-dotenv, opencv-python-headless,
    │                      pytest, httpx, fastapi, uvicorn[standard], python-multipart
    ├── .venv/           ← Python 3.12.13 venv (tüm komutlar ./.venv/bin/... ile)
    ├── .env             ← gerçek env (gitignored); şablon: backend/.env.example
    ├── backend/app/     ← FastAPI servisi (aşağıda §5-6)
    ├── scripts/         ← offline RAG hazırlığı + CLI + document_parser paketi (§7)
    ├── data/            ← korpus + Chroma index + runtime DB (§8)
    ├── tests/           ← 16 dosya, 149 test (§9)
    └── frontend/        ← BOŞ (tek satır README) — henüz yapılmadı
```

**Import kökleri (kritik):** backend paketi `code/` kökünden import edilir (`from backend.app...`), document_parser `code/scripts/` kökünden (`from document_parser...`). `tests/conftest.py` ve `routers/transactions.py` bu iki yolu `sys.path`'e ekler. Testler ve komutlar **`code/` dizininden** çalıştırılır.

## 4. Uçtan uca akış — hangi adım hangi kodda

| Adım | Kod |
|---|---|
| 1. Upload (PDF/DOCX/görsel/md/txt) | `backend/app/routers/transactions.py` `POST /api/transactions` — kayıt + token üretimi, cevap hemen döner |
| 2. Markdown'a çevirme | `scripts/document_parser/` — `DocumentConverter.convert()` (hybrid: dijital PDF → sayfa başına <20 karakter ise Tesseract OCR fallback) |
| 3. PII maskeleme + kart taraması | `backend/app/services/privacy.py` — `analyze(text) → PrivacyReport` |
| 4. RAG bağlamı | `backend/app/services/context_builder.py` — `ContextBuilder.build()` → `ContextPack` (altında `rag.py` `Retriever`) |
| 5. LLM extraction | `backend/app/services/extraction.py` — `make_extraction_service()` → Fake veya canlı OpenAI-uyumlu |
| 6. Restore + risk_flags birleştirme | pipeline içinde: `privacy.restore()` + `_merge_risk_flags` (`routers/transactions.py`) |
| 7. Deterministik denetim | `backend/app/services/validator.py` — `validate() → ValidatorReport` → state geçişi |
| 8. Takip politikası | `backend/app/services/tracking_policy.py` + `routers/transactions.py` manager uçları — öneri → yönetici seçimi → kilit |
| 9. Çift onay | `backend/app/routers/approvals.py` — policy kilitli olmadan onay yok; iki onay tamamlanınca havuz ödemesi oluşur |
| 10. Havuz ödemesi (mock) | `backend/app/services/payment_provider.py` — `MockMokaProvider.create_pool_payment` |
| 11. Teslimat kanıtları | `backend/app/routers/delivery.py` — e-irsaliye simülasyonu + video upload (`services/video/` paketi), kanal guard'ları |
| 12. Efektif kanıt + karar | `services/effective_requirements.py` → `services/decision.py` — ikisi de saf; `decide() → DecisionResult` |
| 13. Orkestrasyon + release guard | `backend/app/services/settlement.py` — `evaluate_settlement()`; approval/e-irsaliye/video aynı yolu kullanır |
| 14. Kanıt paketi | `backend/app/services/evidence.py` — `build_bundle()`; `routers/evidence.py` GET endpoint'i |

Pipeline (adım 2-7) `BackgroundTasks`'ta koşar (`run_pipeline`, `transactions.py:456`): kendi DB bağlantısını açar, herhangi bir hatada akış çökmez → state `awaiting_review` + `PIPELINE_ERROR` bulgusu (hat asla sessiz ölmez).

## 5. Backend altyapı katmanı

**`config.py`** — tüm runtime ayarları tek frozen dataclass'ta (`Settings.from_env()`). Alanlar ve env değişkenleri:

| Alan | Default | Env |
|---|---|---|
| `llm_provider` | `"fake"` | `LLM_PROVIDER` (`fake`\|`openai`) |
| `llm_base_url` / `llm_model` / `llm_api_key` / `llm_timeout` | OpenAI URL / `gpt-5.4-mini` / `""` / `60.0` | `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` / `LLM_TIMEOUT` |
| `chroma_dir` | `code/data/processed/embeddings/chroma` | `CHROMA_DIR` |
| `rag_model_name` | `"BAAI/bge-m3"` | `RAG_MODEL` |
| `legal_collection` / `contract_collection` / `security_collection` | `legal_articles` / `contract_examples` / `security_controls` | `RAG_LEGAL_COLLECTION` / `RAG_CONTRACT_COLLECTION` / `RAG_SECURITY_COLLECTION` |
| `payment_provider` | `"mock"` | `PAYMENT_PROVIDER` |
| `video_provider` | `"fake"` | `VIDEO_PROVIDER` (`fake`\|`roboflow`) — video seçimini **bu** yapar |
| `roboflow_api_key` | `""` | `ROBOFLOW_API_KEY` |
| `video_analyzer` | `"fake"` | `VIDEO_ANALYZER` — ⚠️ **ölü alan**: gölgelenen eski `video.py` içindi, artık hiçbir kod okumuyor |
| `db_path` | `code/data/runtime/m4trust.db` | `DB_PATH` |
| `validator_confidence_threshold` | `0.7` | `VALIDATOR_CONFIDENCE_THRESHOLD` |
| `video_advisory_confidence_threshold` | `0.80` | `VIDEO_ADVISORY_CONFIDENCE_THRESHOLD` — ikincil video sinyalinin dikkate alınma eşiği (§3.4) |

`__repr__` API anahtarlarını (`llm_api_key`, `roboflow_api_key`) `***` maskeler; anahtarlar hiçbir yerde loglanmaz. (⚠️ kozmetik bug: repr string'i `...threshold=0.7)video_provider=...` şeklinde bozuk birleştirilmiş — davranışı etkilemez, bkz. §12 tuhaflıklar.)

**`db.py`** — stdlib `sqlite3`, ORM yok. `connect()`: WAL + foreign_keys ON + `Row` factory + `check_same_thread=False`; her çağıran kendi bağlantısını sahiplenir. `init_db()`: `CREATE TABLE IF NOT EXISTS` ile 6 tablo (idempotent), yalnızca `main.py` startup hook'undan tetiklenir. Tablolar:

```sql
transactions(id PK, state, buyer_token, seller_token, manager_token, markdown, masked_markdown, created_at)
extracted_rules(transaction_id, extraction_json, validator_status, validator_report, created_at)  -- append-only, en son kayıt geçerli
tracking_policies(transaction_id PK, recommendation, recommendation_reason_codes, manager_physical_delivery_confirmed,
                  tracking_mode, video_role, status, configured_at, locked_at)   -- transaction başına tek satır
approvals(transaction_id, party, created_at)                    -- party: buyer|seller
events(id PK AUTOINCREMENT, transaction_id, event_type, payload, source, created_at)
mock_payments(transaction_id, other_trx_code, virtual_pos_order_id, status, amount, created_at)
evidence(transaction_id, bundle_json, created_at)
```

`init_db()` additive ve idempotenttir: `manager_token` `PRAGMA table_info(transactions)` kontrolünden sonra nullable `ALTER TABLE` ile eklenir; **eski satırlara token backfill edilmez** ve hiçbir veri sessizce silinmez. Eski bir runtime DB'sinde demo sürmek isteyen `code/data/runtime/m4trust.db`'yi elle siler.

Not: `get_db()` FastAPI dependency'si tanımlı ama **hiçbir endpoint kullanmıyor** — router'lar `connect()` + elle `close()` deseni kullanıyor. Commit sahipliği deseni: `emit`, provider metotları, `_attempt_decision`, `_persist_*` **commit etmez**; commit'i her zaman endpoint veya `run_pipeline` yapar.

**`eventbus.py`** — `emit(conn, transaction_id, event_type, payload, source)`: events tablosuna INSERT (UTC ISO timestamp). On iki event tipi: `contract_extracted`, `rules_validated`, `tracking_policy_recommended`, `tracking_policy_updated`, `tracking_policy_locked`, `buyer_approved`, `seller_approved`, `e_irsaliye_received`, `delivery_video_analyzed`, `payment_decision_created`, `mock_payment_executed`, `dispute_opened`. **`dispute_opened` artık hiçbir otomatik akışta üretilmez** — gerçek (insan kararlı) dispute için ayrılmıştır.

**`main.py`** — `create_app()` factory; startup'ta `init_db`; `GET /health` → `{"status":"ok"}`; router sırası: transactions, approvals, delivery, evidence. Modül seviyesinde `app = create_app()`.

**`schemas/extraction.py`** — §4.2 donmuş şeması, Pydantic v2, tüm modeller `extra="forbid"`. Kök: `ExtractionJSON(contract_id, parties{buyer,seller: Party(name, tax_id)}, commercial_terms(currency: TRY|USD|EUR|OTHER, total_amount, goods[{name,quantity,unit}], delivery_deadline: YYYY-MM-DD|null), payment_rules[{milestone, trigger: approval|e_invoice|delivery_video|manual_review, percentage 0-100, required_evidence: [contract|e_irsaliye|video], source_quote, confidence 0-1}], risk_flags[], needs_manual_review)`.

## 6. Backend servisleri ve router'lar

### privacy.py — §6.7 güvenlik sınırı
- `mask(text) → MaskResult(masked_text, mapping)`: IBAN → EMAIL → PHONE → TCKN → VKN sırasıyla (sıra kritik, rakam çakışmasını önler) `[[PII_<TIP>_<n>]]` token'ları; aynı değer → aynı token (idempotent).
- `analyze(text) → PrivacyReport(masked_text, mapping, detected_types, blocking_findings, risk_flags)`: önce `mask()`, sonra kart taraması — Track1/Track2, **PAN (13-19 hane + Luhn doğrulaması)**, CVV/CVC (bağlam-duyarlı, çift yön), PIN (bağlam-duyarlı). PAN → maskelenir + `PAN_DETECTED` flag; PAN+expiry → `CHD_CONTEXT` flag; CVV/track/PIN → **blocking_findings** (SAD).
- **Kart token'ları (`[[CARD_*]]`) mapping'e hiç girmez** → `restore()` kart verisini hiçbir koşulda geri açamaz.
- `restore(obj, mapping)`: recursive; LLM çıktısındaki placeholder'ları lokalde orijinaline döndürür.

### rag.py + context_builder.py — RAG
- `Retriever(settings, *, client=None, model=None)` düşük seviye araç: sorguyu BGE-M3 ile encode eder (lazy import — chromadb/FlagEmbedding modül seviyesinde YÜKLENMEZ), Chroma'da arar. `Chunk.score` = Chroma **distance** → **düşük değer daha iyi** (bunu similarity sanma!).
- `ContextBuilder(settings, retriever).build(masked_markdown, privacy_report) → ContextPack`: 3 sabit legal query (k=3) + sinyal-tetiklemeli legal query'ler (KVKK/dış-hizmet anahtar kelimeleri) + 1 contract query (ilk 1000 karakter, k=2) + **yalnızca kart sinyalinde** 2 security query (k=2). Dedupe (text-hash + source/madde_no) → kota (legal≤6, contract≤2, security≤2) → ~12.000 karakter limiti → `formatted_for_llm` (`[LEGAL_SOURCE_n]`/`[CONTRACT_EXAMPLE_n]`/`[SECURITY_CONTROL_n]` etiketli). Retriever hatasında query sessizce atlanır (**graceful degradation** — RAG deps kurulu değilse sistem bağlamsız çalışır).

### extraction.py — LLM adapter çifti
- `ExtractionService.extract(masked_markdown, context: ContextPack | None) → ExtractionResult(status: "ok"|"needs_review", data, reason)`.
- `FakeExtractionService`: her zaman sabit fixture (2 kural: %30 approval + %70 delivery_video; 100.000 TRY; 10 adet Endüstriyel Pompa; deadline 2026-09-01). Demo/test güvencesi.
- `OpenAICompatibleExtractionService`: lazy `openai` import; `response_format=json_object` + `temperature=0`; şema hatasında 1 retry, yine olmazsa `needs_review` (fixture'a düşmez!).
- Maskeleme bu modülün işi DEĞİL — upstream garantisi.

### validator.py — deterministik kural kapısı (saf fonksiyon)
`validate(extraction, *, confidence_threshold=0.7) → ValidatorReport(status, findings[{code, severity, message}])`. REJECT > NEEDS_REVIEW > PASS önceliği. Kontroller:

| Kod | Severity | Koşul |
|---|---|---|
| `PERCENTAGE_SUM` | reject | yüzde toplamı ≠ 100 (±0.01, `round(...,2)` ile) |
| `NO_RULES` | reject | payment_rules boş |
| `CARD_DATA_LEAK` | reject | herhangi bir string alanda `[[CARD_` |
| `UNMASKED_PII` | review | çıktıda maskelenmemiş PII/PAN (**`tax_id` alanları muaf** — şemanın meşru alanı) |
| `LOW_CONFIDENCE` | review | herhangi kural confidence < eşik |
| `EMPTY_SOURCE_QUOTE` | review | source_quote boş |
| `LLM_MANUAL_REVIEW` | review | LLM kendisi `needs_manual_review=true` demiş |
| `NON_POSITIVE_AMOUNT` | review | total_amount ≤ 0 |
| `RISK_FLAG` | review | risk_flags'te `CHD_CONTEXT`/`PAN_DETECTED`/`SECURITY` markerı |

### tracking_policy.py + effective_requirements.py — takip politikası
- `recommend_physical_delivery(extraction) → PhysicalDeliveryRecommendationResult` **saf**: fiziksel birim/mal terimleri, sözleşmesel e-irsaliye, teslim/sevkiyat sözcükleri → `yes|no|uncertain` + güvenli reason code'lar (**sözleşme metni taşımaz**). Yalnız öneridir; takip modunu açmaz. `video` tek başına fiziksel teslimat sinyali değildir.
- `create_draft_policy` / `load_tracking_policy` / `update_system_recommendation` / `update_manager_policy` / `lock_manager_policy` — persistence; `validate_manager_policy` saf çatışma denetimi (`physical_delivery=false` ⇒ mode `off`; sözleşmesel kanıt varken fiziksel teslimat kapatılamaz; **sözleşmesel video `document_and_video` zorunlu kılar**).
- `resolve_effective_requirements(extraction, policy) → EffectiveEvidenceRequirements` **saf**: `contractual` (extraction'dan aynen) · `operational` (`document_only`/`document_and_video` → `e_irsaliye`) · `advisory` (`document_and_video` → `video`) · `effective = contractual | operational`. **Advisory video efektif kanıt değildir**; buna karşılık sözleşmesel video hem efektif kanıttır hem de anomali için değerlendirilir (`decide()` video sinyalini advisory ∪ contractual kümesinde arar).

### decision.py — karar motoru (saf fonksiyon)
`decide(extraction, requirements, DeliveryEvidence(e_irsaliye, video), *, video_confidence_threshold, divergence_threshold=0.10) → DecisionResult(action, capture_ratio, rationale, findings, manual_review_required)`. Sıra (ilk eşleşen kazanır): harici efektif kanıt yok → **capture (1.0)** (approval-only) · efektif kanıt eksik → **hold** (`MISSING_REQUIRED_EVIDENCE`) · e-irsaliye yok → **hold** (`PRIMARY_EVIDENCE_MISSING`; video tek başına miktar üretmez) · sözleşme miktarı ≤ 0 → **hold** · teslim miktarı ≤ 0 → **hold** · advisory video yüksek güvenli ayrışma (>%10) veya eşleşmiş hasar → **hold + manual_review_required** (`dispute` DEĞİL) · teslim < sözleşme → **partial_capture** (oran yalnız e-irsaliyeden) · aksi → **capture**. Düşük güvenli video yalnızca `VIDEO_LOW_CONFIDENCE` warning'idir.

### settlement.py — settlement coordinator (I/O sahibi)
`evaluate_settlement(conn, transaction_id, settings) → dict | None`. Approval, e-irsaliye ve video **aynı** yolu kullanır. Fonlanmamış / iki onayı olmayan / policy'si kilitli olmayan / extraction'ı olmayan işlemi sessizce atlar. `hold`ta state `evidence_pending`de kalır ve `payment_decision_created` yazılır; capture/partial'da havuz hâlâ `pool` ise provider çağrılır → `mock_payment_executed` + state `decided`. **Release guard'ın tek adresi burasıdır**; commit çağıranın sorumluluğundadır.

### payment_provider.py — Moka havuz ödeme mock'u
`PaymentProvider` ABC: `create_pool_payment / get_payment_status / approve_pool_payment(capture_ratio) / undo_approve_pool_payment / refund_payment`. `MockMokaProvider(conn)`: `mock_payments` tablosunu ledger olarak kullanır; cevaplar **gerçek Moka şeklinde**: `{"ResultCode":"Success", "Data":{"IsSuccessful":true, "VirtualPosOrderId":"ORDER-<uuid>"}}`; bizim `transaction_id` → `OtherTrxCode`. Status akışı: `pool` → `released`/`partially_released` (→ undo ile `pool`, refund ile `refunded`). `create_pool_payment` idempotent. Gerekçe: gerçek Moka portal'ında havuz ödeme akışı böyle (`IsPoolPayment=1`, `/PaymentDealer/DoApprovePoolPayment`); v1'de gerçek entegrasyon yalnızca adapter altını değiştirir. **Yetki kararı bu modülde yok** — guard çağıranda.

### video/ paketi — VideoAnalyzer (PR #4 ile geldi; ⚠️ entegrasyonu kırık)
`services/video/` paketi: `analyzer.py` (`VideoAnalyzer` ABC + `FakeVideoAnalyzer` + `RoboflowVideoAnalyzer` + `make_video_analyzer` — seçim `settings.video_provider` ile), `frame_sampler.py` (OpenCV kare örnekleme), `detectors.py` + `roboflow_client.py` (iki Roboflow-hosted YOLOv8 modeli, düz `requests` REST: `logistics-sz9jr/2` koli/palet sayımı, `detecting-a-damaged-parcel/11` hasar), `correlator.py` (hasar tespitini merkez-noktası koli kutusuna düşüyorsa o koliye bağlar), `interfaces.py`/`exceptions.py`. Uzantıya göre video/görsel dispatch tek `analyze()` girişinden. Bilinen model sınırları ARCHITECTURE §3.4'te (istiflenmiş palette eksik sayım; 7 gerçek fotoğrafla doğrulama notları).

**Kanıt sözleşmesi:** `analyze()` → `{counts, unit_count, damage_signals, confidence}`. `counts` sınıf başına ham dökümdür (kanıt/UI); **`unit_count`** taşıyıcı sınıfları (palet) dışlayan teslim birimi sayısıdır ve karar motorunun okuduğu tek sayıdır — böylece `decision.py` model sınıf adlarını bilmez. `FakeVideoAnalyzer` dosya-adı ipuçları: `eksik` → `unit_count=7` (nicel ayrışma), `hasarli` → eşleşmiş hasar sinyali, `dusuk_guven` → `confidence=0.5` (eşik altı). ⚠️ Eski `services/video.py` dosyası hâlâ diskte ama `video/` paketi onu **gölgeler** — ölü koddur, silinmesi bekliyor.

### evidence.py — kanıt paketi
`build_bundle(conn, transaction_id) → dict`: transaction özeti (**yalnızca id/state/created_at** — markdown/token'lar girmez), en son extraction, validator raporu, onaylar, tüm event zinciri, mock ödeme kayıtları, en son karar payload'ı, `generated_at`. **Girmeyenler:** ham markdown, masked_markdown, token'lar, maskeleme haritası (zaten persist edilmez), `tax_id`. Extraction `services/extraction_projection.py`den geçer; `source_quote` **maskelenmiş** biçimde korunur (`privacy.analyze()`) çünkü bundle capability token'ıyla indirilir. Token istemeyen `GET /{id}` ucu alıntıyı hiç döndürmez: maskeleme desen tabanlıdır, NER değildir.

### Router'lar — §4.1'in 11 endpoint'i

| Endpoint | Davranış / hata kodları |
|---|---|
| `POST /api/transactions` (multipart `file`) | İzinli uzantılar: `.pdf .docx .png .jpg .jpeg` + `.md .txt` (passthrough); değilse **400**. Cevap hemen: `{id, buyer_link, seller_link, manager_link}`; draft/off policy açılır; pipeline arka planda |
| `GET /api/transactions` | Liste: id, state, created_at, taraf adları (extraction'dan) |
| `GET /api/transactions/{id}` | Detay: **redacted** extraction (token istemez ⇒ `source_quote` DÖNMEZ), validator, event timeline, ödeme; yoksa **404** |
| `GET .../party-view?token=…` | Token → party çözümü; kural özeti + validator bulguları + onay durumu + `tracking_summary`; yanlış token **403** |
| `GET .../manager-view?token=…` | Sistem önerisi + reason code'lar, policy durumu, sözleşmesel kanıt şartları, `ready_for_policy`; **taraf token'ı 403** |
| `PUT .../tracking-policy` body `{manager_token, physical_delivery_confirmed, tracking_mode}` | Taslak policy günceller (idempotent, aynı seçimde `updated=false`); yalnız validator PASS + state `awaiting_approval` iken; `tracking_policy_updated` event |
| `POST .../tracking-policy/lock` body `{manager_token}` | Policy'yi kilitler (idempotent, `locked_at` korunur); `tracking_policy_locked` event |
| `POST .../approvals` body `{token}` | İdempotent onay + `{party}_approved` event; yanlış token **403**; `rejected` **409**; **policy kilitli değilse 409 `POLICY_NOT_LOCKED`**. İki onay → `create_pool_payment` + state=`active` → `evaluate_settlement` |
| `POST .../events/e-irsaliye` body `{delivered_quantity}` | Kanal etkin değilse **409 `TRACKING_NOT_ENABLED`**; `decided` ise **409 `TRANSACTION_DECIDED`**; fonlanmamışsa **409**; `e_irsaliye_received` event + `evaluate_settlement` |
| `POST .../delivery-video` (multipart) | Aynı guard'lar (**analizden önce**); **inline** analiz (cevap güncel kararı taşısın diye), orijinal dosya adı temp dosyada korunur; `delivery_video_analyzed` event + `evaluate_settlement` |
| `GET .../evidence?token=…` | Bundle döner (tracking policy snapshot'ı dahil) + her çağrıda `evidence` tablosuna snapshot yazar; buyer/seller/manager token'larından biri zorunlu (**403**), işlem yoksa **404** |

Policy/delivery 409'ları her zaman `detail: {code, message, conflicts[]}` gövdesiyle döner (`POLICY_NOT_CONFIGURABLE` · `POLICY_LOCKED` · `POLICY_INVALID` · `POLICY_CONTRACT_CONFLICT` · `POLICY_NOT_LOCKED` · `TRACKING_NOT_ENABLED` · `TRANSACTION_DECIDED`).

**Release guard (§6.1'in kod hali):** artık router'da değil, `services/settlement.py::evaluate_settlement` içindedir — ödeme yalnızca `{"buyer","seller"} ⊆ onaylayanlar ∧ state ∈ {active, evidence_pending} ∧ policy locked ∧ havuz hâlâ `pool`` iken yürütülür. `hold`'da capture asla çağrılmaz ve işlem `evidence_pending`de kalır.

**State machine:** `uploaded → extracting → {awaiting_approval (PASS) | awaiting_review (NEEDS_REVIEW/hata) | rejected (REJECT)} → (policy locked) → active → [evidence_pending] → decided`. Approval-only işlem `active`ten doğrudan `decided`e geçer. Policy yaşam döngüsü (`draft|locked`) transaction state'inden ayrıdır. **Not:** `awaiting_review`da onay artık kabul edilmez (policy yalnız PASS + `awaiting_approval` iken kilitlenebilir); NEEDS_REVIEW'un çözümü ayrı bir iştir.

## 7. Offline scripts katmanı (`code/scripts/`)

Offline hazırlık zinciri (korpus değişince elle çalıştırılır): 

1. `convert_documents.py <dosya>` — tek dosyayı markdown'a çevirir (stdout).
2. `chunk_documents.py` (argümansız) — `data/processed/markdown/**/*.md` → `data/processed/chunks/**/*.json`. İki strateji: `**MADDE N**` bazlı (mevzuat; GEÇİCİ/EK MADDE dahil) → yoksa başlık bazlı fallback.
3. `build_rag.py` (argümansız) — chunk'ları BGE-M3 ile embed edip Chroma'ya upsert eder. Koleksiyon yönlendirme dizinden: `contracts/` → `contract_examples`, `security/` → `security_controls`, geri kalan → `legal_articles`.
4. `extract_contract.py <dosya> [--provider fake|openai] [--out f.json]` — tam extraction hattının CLI'ı (backend API'siyle aynı servisleri kullanır). Çıkış kodları: 0 ok, 1 hata, 2 needs_review. `--collection` **deprecated** (tek-koleksiyon debug bypass). Dayanaklar özeti stderr'e basılır, stdout temiz JSON'dur.

`document_parser/` paketi (Clean Architecture, backend'in de kullandığı dönüştürücü): `TextExtractor` ABC → `DigitalPdfExtractor` (PyMuPDF) / `OcrPdfExtractor` (Tesseract, dil `tur`, DPI 300) / `HybridPdfExtractor` (sayfa başına <20 karakter → OCR fallback) / `DocxExtractor` → `ExtractorFactory` (uzantı registry) → `DocumentConverter` (facade) → `MarkdownNormalizer`. Hata hiyerarşisi: `DocumentParserError` → `UnsupportedFileTypeError` / `ExtractionError` / `EmptyDocumentError`.

**Bağımlılık yönü:** `scripts/extract_contract.py` backend paketlerini import eder (backend → scripts yönünde yalnızca `document_parser` köprüsü vardır, `routers/transactions.py` sys.path ile).

## 8. Veri katmanı (`code/data/`)

- `raw/legal/` — 8 mevzuat PDF'i (6493, TBK 6098, 5549, KVKK, TCMB Yönetmelik 39080, TCMB Tebliğ 39081; ⚠️ Tebliğ ve Yönetmelik'in birer boyut-eş duplikesi var: `tebliğ.pdf`≈`teblig_39081_...pdf`, `Yönetmelik.pdf`≈`yonetmelik_39080_...pdf`).
- `raw/contracts/` — 7 örnek sözleşme PDF'i (markdown korpusundaki 31'in alt kümesi; kalanı başka kaynaktan işlenmiş).
- `processed/markdown/` — 6 legal .md (kökte) + `contracts/` 31 .md + `security/pci_dss_control_map.md` (ekibin kendi cümleleriyle 6 PCI DSS kontrolü — ham standart metni lisans gereği repoya giremez).
- `processed/chunks/` — legal 891 chunk · contracts 421 chunk (⚠️ **395 benzersiz chunk_id** — aynı stem'li dosyalarda `heading-N` id çakışması, upsert 395'e daraltır) · security 7 chunk.
- `processed/embeddings/chroma/` — **yalnızca 2 koleksiyon embed'li:** `legal_articles` (891 vektör) ve `contract_examples` (395 vektör). **`security_controls` koleksiyonu HENÜZ YOK** — chunk'lar diskte hazır ama ortamda chromadb/FlagEmbedding kurulu olmadığından `build_rag.py` yeniden çalıştırılmadı. ContextBuilder bu durumda security query'lerini sessizce atlar (graceful).
- `runtime/m4trust.db` — SQLite runtime DB (gitignored).
- `synthetic/`, `processed/cleaned/` — boş.

## 9. Test katmanı (`code/tests/`) — 214 test (214 passed / 0 failed)

Çalıştırma: `cd code && ./.venv/bin/python -m pytest -q` → **214 passed** (10.07.2026'da doğrulandı; video bağımlılıkları `requests`/`opencv-python-headless`/`python-dotenv` venv'e kurulu olmalı, yoksa 4 video test modülü collect edilemez). Ayrı pytest config dosyası yok; sys.path düzeni `conftest.py`'de. Paylaşılan E2E fixture'ları: `tests/extraction_fixtures.py` (sözleşmesel video · bozuk yüzde · `patch_extraction` yardımcısı).

| Dosya | Kapsam |
|---|---|
| `test_api_flow.py` (11) | TestClient uçtan uca: upload→pipeline→policy kilidi→onay→havuz; 404/403; **altı demo senaryosu** (A approval-only · B document-only · C uyumlu video · D anomali→hold · E sözleşmesel video · F REJECT) |
| `test_delivery_flow.py` (15) | Kanal guard'ları (`TRACKING_NOT_ENABLED`/`TRANSACTION_DECIDED`), e-irsaliyeden capture/partial, advisory video dalları, ikinci release olmadığı, bundle'da ham markdown/token olmadığı |
| `test_tracking_policy.py` (6) / `test_effective_requirements.py` (3) / `test_manager_policy_api.py` (9) | Draft/off default + manager token sızmaması · öneri reason code'ları · saf resolver matrisi · manager capability, lock idempotency, contract conflict, public redaksiyon |
| `test_validator.py` (19) | Tüm validator kontrolleri + tolerans sınırları + reject>review önceliği |
| `test_decision.py` (12) | Policy-aware karar matrisi: approval-only capture, e-irsaliye full/partial, video-only hold, düşük/yüksek güvenli anomali, sözleşmesel video, eşik env override'ı |
| `test_payment_provider.py` (10) | Mock ledger: create idempotent, full/partial release, undo, refund, failure şekilleri |
| `test_privacy.py` (10) / `test_privacy_card_data.py` (16) | PII mask/restore round-trip; PAN Luhn, kart token'ı restore edilmez, CVV/PIN/track blocking, CHD flag |
| `test_context_builder.py` (12) | Query planlama, kota/dedupe/limit, kart sinyali→security, `BrokenRetriever` graceful |
| `test_extraction.py` (9) | Fake/canlı adapter, retry, context enjeksiyonu (fake OpenAI client zinciri) |
| `test_extract_contract_cli.py` (9) | CLI hattı: maskeli gönderim (SpyExtractionService), blocking'de canlı atlanır, exit code'lar |
| `test_extraction_schema.py` (10) | §4.2 şema doğrulamaları, extra alan reddi, **donmuş alan adı + enum snapshot'ı** |
| `test_converter/extractors/factory/normalizer.py` (21) | document_parser katmanları |
| `test_video_analyzer/correlator/detectors/frame_sampler/interfaces/roboflow_client.py` (~30) | Yeni video paketi: analyzer dispatch, korelasyon, detector parse, Roboflow client (mock REST), kare örnekleme |

Önemli desen: **API testleri `with TestClient(app) as c:` bağlam yöneticisiyle koşmalı** — lifespan/`init_db` yalnızca böyle tetiklenir. Dış bağımlılıklar hiçbir testte gerekmez (hepsi fake/DI).

## 10. Çalıştırma kılavuzu

```bash
cd code

# Testler (video deps kurulu değilse önce: ./.venv/bin/pip install requests python-dotenv opencv-python-headless)
./.venv/bin/python -m pytest -q                     # 171 passed / 8 failed beklenir (bkz. §12 bilinen kırık)

# API'yi kaldır (tek worker! WAL + BackgroundTasks tasarımı çoklu worker'a göre değil)
./.venv/bin/uvicorn backend.app.main:app --reload   # http://127.0.0.1:8000/docs

# CLI ile tek sözleşme extraction (fake provider, anahtar gerekmez)
./.venv/bin/python scripts/extract_contract.py data/raw/contracts/sales/"Sözleşme Örneği.pdf"

# Canlı LLM için: backend/.env.example → code/.env kopyala, LLM_PROVIDER=openai + LLM_API_KEY doldur
# Canlı video analizi için: VIDEO_PROVIDER=roboflow + ROBOFLOW_API_KEY (default fake, ağa çıkmaz)
# Canlı RAG için: pip install -r requirements.txt (chromadb+FlagEmbedding/torch, ~GB'lar; kurulu değilse
#   pipeline RAG'siz graceful çalışır) — kurunca security koleksiyonu için: python scripts/build_rag.py
```

Demo curl sırası: `POST /api/transactions` (dosya) → `GET /api/transactions/{id}` (extraction+validator) → `GET .../manager-view?token=…` (sistem önerisi) → `PUT .../tracking-policy` `{manager_token, physical_delivery_confirmed, tracking_mode}` → `POST .../tracking-policy/lock` `{manager_token}` → 2× `POST .../approvals` (buyer/seller token — upload cevabındaki linklerden) → *(takip açıksa)* `POST .../events/e-irsaliye` `{"delivered_quantity": 10}` → `GET .../{id}` (decided/captured) → `GET .../evidence`. **Takip `off` ise** iki onay yeterlidir; teslimat uçları 409 döner.

## 11. Süreç kuralları (koda dokunmadan önce)

1. **Plan yaşam döngüsü:** durum = klasör. `plans/planning/` (taslak) → `plans/ready/` (kullanıcı onayıyla) → uygulama (`/plan-uygula` komutu) → implementer handoff'u `plans/review/` → kabul sonrası `plans/done/`. Planner planning'e yazar; **ready'ye taşıma kararı kullanıcınındır.**
2. **Doc-sync protokolü (atlanamaz):** koda dokunan her iş, eskittiği dokümanı günceller — endpoint→ARCHITECTURE §4.1, şema→§4.2 (mutabakat şart), event→§4.3, modül→§1, bağımlılık→§2, tablo/state→§5, değişmez kural→§6+AGENTS. "Doc-sync yapılmadan iş bitti sayılmaz."
3. **Çelişki kontrolü önce:** yapacağın iş ARCHITECTURE §6'yı deliyorsa durup kullanıcıya sor.
4. **Commit sahipliği kullanıcıdadır** — ajanlar commit/push etmez (aksi söylenmedikçe); iş feature branch'te bekletilir.
5. Ekip 2 kişi, süre 5-6 gün — kapsam eklerken bunu hesaba kat; görevler kişiye etiketlenmez.

## 12. Şu anki durum (10.07.2026, master `ab61526`)

**Bitti ve doğrulandı:** offline RAG hattı · document_parser · extraction hattı (fake+canlı) · privacy + kart guardrail · ContextBuilder · backend omurgası (FastAPI, 7 tablo, eventbus, 11 endpoint, validator, decision, MockMoka, evidence) · gerçek video analiz paketi (Roboflow YOLOv8) · **tracking policy + settlement coordinator** (manager capability, policy lock, advisory video semantiği).

**Git durumu:** `master`'dayız; PR #4 (`yusuf-video-analyzer`) ve PR #5 (`feature/backend-iskeleti`) merge edilmiş. Tracking policy işi working tree'de commit'lenmemiş durumda (commit sahipliği kullanıcıdadır).

**✅ Önceki "video counts" kırığı giderildi:** analyzer `unit_count` (taşıyıcı sınıflar hariç teslim birimi) döndürüyor ve `decision.py` yalnızca onu okuyor; `FakeVideoAnalyzer` dosya-adı ipuçları `eksik` (nicel ayrışma) · `hasarli` (eşleşmiş hasar) · `dusuk_guven` (eşik altı güven) demo dallarını sürüyor. Suite tamamen yeşil (214 passed).

**Eksik / sıradaki işler (öncelik sırasıyla):**
1. **Frontend — hiç yok.** React+Vite+Tailwind; route'lar ARCHITECTURE §1'de tanımlı: `/` (dashboard+upload), `/t/:id` (detay+demo aksiyonları), `/t/:id/party?token=…` (taraf onayı), `/t/:id/manager?token=…` (yönetici policy paneli). Tüketeceği API hazır; **ayrı bir plan yazılacak** (video-merkezli anlatımın kaldırılması, koşullu delivery/video kontrolleri, 409 kodlarının anlaşılır gösterimi).
2. **Manuel inceleme çözümü.** `hold + manual_review_required` üretiliyor ama yöneticinin bunu çözecek bir aksiyonu (devam et / yeni kanıt iste / dispute aç / iade) **yok** — işlem `evidence_pending`de kalır. Ayrı plan.
3. **`security_controls` embed'i** — chunk'lar hazır; RAG deps kurulu ortamda `build_rag.py` + koşullu retrieval duman testi.
4. **`document_parser` relokasyonu** — ARCHITECTURE §1 `services/documents/` öngörür; şimdilik sys.path köprüsü (bilinçli, kayıtlı sapma). Ölü `services/video.py`'nin silinmesi de bu temizlik kalemine ait.
5. **Açık kaynak model benchmark notebook'u** (ar-ge eki) + demo provası/ekran kaydı fallback'i.

**Bilinen sınır (kayıtlı, bilinçli):** `document_and_video` modunda video gelmeden e-irsaliye tek başına capture üretebilir — bu, videonun gerçekten opsiyonel olmasının doğal sonucudur. Karar verilmiş işleme geç gelen video `TRANSACTION_DECIDED` ile reddedilir. Grace period / explicit "değerlendir" aksiyonu ayrı plana bırakıldı.

**Açık dış bağımlılık:** Moka mentor sorusu (wallet contract'ı public havuz contract'ından farklı mı; dispute'ta havuz parasının akıbeti) — cevap gelirse yalnızca `MockMokaProvider`'ın iç şekli etkilenir.

**Bilinen tuhaflıklar (davranışı bozmayan, kayıtlı):** `get_db` dependency'si kullanılmıyor (elle bağlantı deseni tercih edildi) · fake fixture artık approval-only (`required_evidence=[contract]`), teslimat kanıtı yalnız takip politikasıyla devreye girer · `settlement.py` event payload'ını ararken `event_type LIKE '%video%'`/`'%e_irsaliye%'` kullanır (bugün tek eşleşme var, yeni event adlandırırken dikkat) · eski `services/video.py` diskte duruyor ama `video/` paketi tarafından gölgeleniyor (ölü kod) · `Settings.video_analyzer` alanı ve `VIDEO_ANALYZER` env'i ölü (seçimi `video_provider` yapar) · `Settings.__repr__` çıktısı bozuk birleştirilmiş (kozmetik) · `raw/legal`'de iki duplike PDF · contracts chunk id çakışması (421→395) · Chroma'da boş bir eski segment dizini · SAD blocking guard'ı yalnızca `llm_provider=="openai"` iken canlı çağrıyı keser (fake'te veri dışarı gitmediği için extraction çalışır, sonuç yine needs_review işaretlenir).
