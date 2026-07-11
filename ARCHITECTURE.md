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
  → TrackingPolicy (yönetici fiziksel teslimat takibini seçer ve KİLİTLER)
  → Çift taraflı onay (token'lı taraf linkleri)
  → PaymentProvider.create_pool_payment (para havuzda bekler)
  → Teslimat kanıtları (e-irsaliye birincil nicel kanıt, video ikincil/advisory)
  → Settlement coordinator → decision engine → capture / partial / hold
  → PaymentProvider aksiyonu + evidence bundle
```

Sistem sözleşmeden fiziksel teslimatı yalnızca **önerir**; takip modunu (`off` · `document_only` · `document_and_video`) yönetici seçer ve taraf onaylarından önce kilitler. Sözleşmenin kendi kanıt şartları (extraction'daki `required_evidence`) yönetici tercihiyle devre dışı bırakılamaz. Ayrıntı: §5, §6.9-6.11.

```
code/
├── scripts/          # offline hazırlık + demo_moka_contract.py gerçek HTTP demo sürücüsü
├── backend/app/
│   ├── main.py · config.py · eventbus.py
│   ├── db/           # connection lifecycle · migration runner · kısa transaction helper · migrations 001,003-010
│   ├── repositories/ # transactions · identity/participants · documents/extraction_runs · rule_sets · reviews
│   ├── api/          # yeni uçlar için standart hata zarfı
│   ├── middleware/   # request-id üretimi ve X-Request-ID response header'ı
│   ├── schemas/      # extraction.py (ikili sözleşme) · tracking/identity/participants · rule_sets/reviews
│   ├── routers/      # transactions (+ manager/policy uçları) · approvals · delivery · evidence ·
│   │                 # auth · entities · participants · invitations (Plan 03) · reviews (Plan 04 Wave A)
│   └── services/
│       ├── documents/         # DocumentExtractor: pdf_digital · docx · ocr · normalizer
│       ├── rag.py             # Chroma retrieval (BGE-M3 lazy singleton, düşük seviye)
│       ├── context_builder.py # ContextBuilder: çoklu-query/çoklu-koleksiyon RAG orkestrasyonu → ContextPack
│       ├── privacy.py         # maskeleme (mask/restore) + kart-verisi guardrail (analyze/PrivacyReport)
│       ├── extraction.py      # ExtractionService: LLMClient + FakeExtractionService
│       ├── document_storage.py# DocumentStorageProvider + local immutable storage adapter'ı
│       ├── transaction_pipeline.py # account/legacy extraction pipeline orkestrasyonu
│       ├── rule_versions.py   # frozen RuleVersionService: immutable version + validator sonucu
│       ├── review.py          # frozen ReviewService: case/action lifecycle
│       ├── reconciliation.py  # extracted/declared/confirmed party diff + blocking review case
│       ├── auth.py            # Argon2id parola · session/CSRF token (yalnız hash) · Origin doğrulaması
│       ├── identity.py        # legal entity + membership: AES-256-GCM tax ID + HMAC lookup
│       ├── access_control.py  # ActorContext (anonymous · legacy_capability · user/session) + auth/membership guard'ları
│       ├── participants.py    # ParticipantService (frozen, v2 §8.1): attach_creator/placeholder/accept_invitation
│       ├── invitations.py     # davet yaşam döngüsü: create/preview/revoke (accept ParticipantService'te)
│       ├── notifications.py   # NotificationProvider portu + FakeNotificationProvider
│       ├── audit.py           # audit_events persistence (business mutation ile aynı connection/transaction)
│       ├── transaction_state.py # legacy_v1 → canonical state saf projeksiyonu (v2 §2.8)
│       ├── extraction_projection.py # public API'ler için redacted extraction görünümü (tax_id yok, source_quote maskeli)
│       ├── validator.py       # deterministik kural kapısı
│       ├── tracking_policy.py # TrackingPolicy persistence + deterministik fiziksel teslimat önerisi
│       ├── effective_requirements.py # saf resolver: contractual + operational + advisory kanıt kümeleri
│       ├── video/             # VideoAnalyzer: FakeVideoAnalyzer + RoboflowVideoAnalyzer (§3.4)
│       ├── payments/          # provider-bağımsız PaymentGateway port/domain + Moka adapter'ları
│       ├── decision.py        # decision engine — saf fonksiyon, I/O yok
│       ├── settlement.py      # settlement coordinator: karar + release guard + event/ödeme orkestrasyonu
│       ├── payment_provider.py# PaymentProvider: MockMokaProvider + RealMokaProvider(v1)
│       └── evidence.py        # zaman damgalı JSON bundle (tracking policy snapshot'ı dahil)
├── backend/mock_moka/         # ayrı FastAPI process'i: contract-faithful local Moka simulator
└── frontend/src/     # api/ · pages/ (Dashboard · TransactionDetail · PartyReview · ManagerPolicy) · components/
```

> **Uygulama notu (2026-07-09):** `DocumentExtractor` şu an `services/documents/` altında değil — mevcut kod `code/scripts/document_parser/` içinde (Clean Architecture, testli); backend pipeline onu bir `sys.path` köprüsüyle import eder (bkz. `routers/transactions.py`). Yukarıdaki `services/documents/` hedef yapısı korunur; relokasyon ayrı bir iştir. Backend omurgası (`main`/`db`/`eventbus`/`routers`/`validator`/`decision`/`payment_provider`/`video`/`evidence`) kuruldu — [plans/done/backend_iskeleti_ve_islem_akisi.md](plans/done/backend_iskeleti_ve_islem_akisi.md).

> **Uygulama notu (2026-07-11, Plan 03):** Identity/session/legal-entity/membership + participant/invitation/audit + transaction ownership cutover kuruldu — [plans/done/03_identity_legal_entity_party_onboarding.md](plans/done/03_identity_legal_entity_party_onboarding.md). İki paralel `lifecycle_version` sistemi bir arada yaşıyor: **`legacy_v1`** (anonim capability-link, tüm mevcut davranış değişmedi) ve **`account_v2`** (authenticated session + legal entity + participant/invitation, capability token üretmez). `POST /api/transactions` iki modu da aynı uçta additive olarak sunar (§4.1). `main.py`'ye `auth`/`entities`/`participants`/`invitations` router'ları bu entegrasyon checkpoint'inde eklendi.

> **Uygulama notu (2026-07-11, Plan 04 Wave A):** Document provenance (`contract_documents`), immutable extraction runs, immutable/validator-bound rule-set versions ve manual review/reconciliation çekirdeği kuruldu. Migration runner `008 → 009 → 010` sırasını uygular; reviews router gerçek app'e bağlıdır. Account pipeline'da validator `NEEDS_REVIEW` sonucu blocking `validator` case açar; participant confirm current rule-set ile party reconciliation çalıştırır. Merkezi `repositories/rule_sets.py::get_current` reader'ı transactions/delivery/settlement yanında approvals/evidence tarafından da kullanılır. `ExtractionJSON` şeması değişmedi; legacy `extracted_rules` fallback'i korunur.

Frontend route'ları: `/` (dashboard + upload) · `/t/:id` (işlem detayı, demo aksiyonları) · `/t/:id/party?token=…` (taraf görünümü: diff + kural özeti + takip özeti + onay) · `/t/:id/manager?token=…` (yönetici: fiziksel teslimat doğrulaması + takip modu + policy kilidi). Authenticated account akışının frontend'i Plan 03 kapsamı dışıdır (Program 6/Faz 08).

## 2. Tech stack

| Katman | Karar |
|---|---|
| Backend | Python 3.12 · FastAPI + uvicorn · SQLite (stdlib `sqlite3`, WAL, tek worker) · upload için `python-multipart` · Moka HTTP için sync `httpx` + Decimal JSON için `simplejson` · test için `httpx`/`TestClient` (arka plan işleri: `BackgroundTasks`, queue altyapısı yok). Bağımlılıklar `requirements-core/ci/rag/video.txt` profillerine ayrılır; CI ağır RAG/video profilini kurmaz. |
| Frontend | React · Vite · Tailwind |
| Doküman | PyMuPDF/PyMuPDF4LLM (dijital PDF) · python-docx/mammoth (DOCX) · Tesseract (OCR) |
| RAG | BAAI/bge-m3 + ChromaDB — koleksiyonlar `legal_articles` · `contract_examples` · `security_controls` (koşullu), `code/data/processed/embeddings/chroma/`. Orkestrasyon: `context_builder.py` |
| LLM | `gpt-5.4-mini` (OpenAI-uyumlu API, `openai>=1.40` SDK, lazy import) — structured output (`response_format=json_object` + Pydantic şema doğrulama, uymazsa 1 retry → NEEDS_REVIEW). `LLM_PROVIDER=fake\|openai` env ile seçilir (default `fake`) |
| Video | OpenCV frame sampling + Roboflow hosted YOLOv8 (koli/palet: `logistics-sz9jr`, hasar: `detecting-a-damaged-parcel`) — bkz. §3.4 |
| Ödeme | Moka United havuz ödeme contract'ı (mock'lanır, bkz. §3.3) |

## 3. Model ve dış servis iletişimi

Kural: **tüm dış bağımlılıklar adapter interface arkasındadır ve her birinin Fake/Mock implementasyonu vardır.** Seçim env ile yapılır; uygulama akışı hangi implementasyonun çalıştığını bilmez.

### 3.1 LLM — `ExtractionService`

```python
ExtractionService.extract(masked_markdown: str, context: ContextPack | None) -> ExtractionResult
```

- Girdi **maskelenmiş** markdown + `ContextPack`'tir (`context_builder.py`, §3.2); ham dosya asla dış API'ye gitmez. `context=None` veya boş pack → bağlamsız çağrı. Kaynaklı bağlam LLM'e `formatted_for_llm` olarak, kaynak-tipi etiketleriyle (`[LEGAL_SOURCE_n]` / `[CONTRACT_EXAMPLE_n]` / `[SECURITY_CONTROL_n]`) tek system mesajında verilir.
- Çıktı §4.2'deki şemaya zorlanır (structured output). Şemaya uymayan cevap retry edilir, yine uymazsa NEEDS_REVIEW.
- LLM çıktısı validator'dan geçmeden DB'ye aktif kural olarak yazılmaz. Provider tek dosyada izole — model değişimi diğer kodu etkilemez.

### 3.2 RAG — Chroma + BGE-M3

- Korpus BGE-M3 ile embed'lidir; **sorgu da BGE-M3 ile encode edilmek zorundadır.** Model lazy singleton (ilk istekte yüklenir, süreçte kalır, CPU/`use_fp16=False`).
- RAG yalnızca retrieval yapar; hukuki yorum ve karar üretmez.
- `Retriever` (rag.py) düşük seviye tek-query/tek-koleksiyon araçtır; **`ContextBuilder`** (context_builder.py) onu sarmalar: rule-based çoklu query planlama (sabit temel + sinyal-tetiklemeli), `legal_articles` + `contract_examples` + (yalnızca kart/güvenlik sinyalinde) `security_controls` retrieval, dedupe + kaynak-tipi kotası (legal≤6 · contract≤2 · security≤2) + ~12k karakter limiti → `ContextPack`. `Chunk.score` Chroma **distance**'ıdır (düşük daha iyi); bu semantik `ContextSource.score`'da korunur. Retriever/koleksiyon yoksa ilgili query sessizce atlanır (graceful, bağlamsız/kısmi devam).

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
- Release çağrısı yalnızca şu koşulda yapılır: `buyer_approved ∧ seller_approved ∧ decision ∈ {capture, partial_capture} ∧ state ∈ {active, evidence_pending} ∧ havuz ödemesi hâlâ `pool``. Bu guard tek bir yerde, `services/settlement.py::evaluate_settlement` içinde yaşar; router'lar ödeme mantığının sahibi değildir. Ayrıntı ve gerekçe: `plans/planning/moka_cüzdan_entegrasyonu.md`.
- **M0 hazırlığı (2026-07-10):** `services/payments/domain.py` ve `ports.py`, provider-bağımsız `PaymentGateway` sözleşmesini, Moka standard capability profilini ve enjekte edilebilir store kullanan ağsız `FakePaymentGateway`'i tanımlar. Bu port mevcut `PaymentProvider` akışına **bağlı değildir**; `MockMokaProvider`, router'lar ve settlement Moka funding-unit cutover'ına (Plan 06) kadar değişmeden kalır.
- **M1 HTTP client (2026-07-11):** `services/payments/moka/{authentication,serialization,client,mapper,redaction}.py`, frozen PaymentDealer DTO'larıyla gerçek sync HTTP POST konuşur. CheckKey SHA-256 contract'ına uyar; minor-unit tutarlar Decimal JSON number'a çevrilir; create/approve timeout'ı `unknown` sonuç üretir ve request/response trace'i secret/PII maskeli tutulur. `PAYMENT_PROVIDER=moka_http` ayarı tanınır ancak client bu fazda mevcut provider factory/settlement yoluna **bağlanmaz**.
- **M1C demo topolojisi (2026-07-11):** `backend.mock_moka.app:app` port 8001'de ayrı uvicorn process'i olarak çalışır; `scripts/demo_moka_contract.py` aynı client'la gerçek HTTP üzerinden create → approve → detail zincirini ve `--fault` ile beklenen banka reddini gösterir. Stdout yalnız redacted request/response JSON çiftlerini içerir. Client↔mock E2E paketi create → approve → already-approved → undo → detail reconcile zincirini, negatifleri ve secret leakage'i doğrular (7/7); tam suite 303/303'tür. Bu yan panel ana FastAPI app'ine register edilmez ve settlement cutover'ı yapmaz.

### 3.4 Video — `VideoAnalyzer`

`analyze(media_path) -> {counts, unit_count, damage_signals, confidence}` → `delivery_video_analyzed` event'i. `counts` sınıf başına ham dökümdür (kanıt/UI); `unit_count` taşıyıcı sınıflar (palet) hariç teslim birimi sayısıdır — decision engine yalnızca onu okur, model sınıf adlarını bilmez. `VIDEO_PROVIDER=fake|roboflow` (demo'da `fake`) — Fake ağa çıkmaz, dosya adı ipuçlarıyla (`eksik` · `hasarli` · `dusuk_guven`) dört karar dalını sürer.

**Video advisory semantiği (bağlayıcı, 2026-07-10):** Platformun opsiyonel video takibi (`tracking_mode=document_and_video`) her zaman `video_role=advisory`'dir. Advisory video:

- `effective_required_evidence` kümesine **girmez**; yokluğu tek başına `hold` üretmez (`VIDEO_NOT_PROVIDED`, bilgilendirici).
- Teslim edilen miktarın kaynağı **olamaz**: `delivered_quantity = video.unit_count` yapılmaz; capture/partial oranı yalnız e-irsaliyeden (veya sözleşmesel başka bir birincil kanıttan) hesaplanır.
- `VIDEO_ADVISORY_CONFIDENCE_THRESHOLD` (default `0.80`) altındaki güvende yalnızca **warning** üretir (`VIDEO_LOW_CONFIDENCE`); sayım ve hasar sinyalleri karar verdirmez.
- Eşik üstünde: e-irsaliye ile sayım ayrışması sözleşme miktarının %10'unu aşarsa (`VIDEO_COUNT_DIVERGENCE`) veya ilgili koliyle **eşleşmiş** hasar sinyali varsa (`VIDEO_DAMAGE_MATCHED`) → `hold` + `manual_review_required`. **Otomatik `dispute` açılmaz**; dispute, yetkili insanın ticari kararıdır.
- Sözleşme videoyu açıkça şart koşuyorsa (`required_evidence: ["video"]`) video advisory değil **zorunlu kanıttır**: yönetici bunu kapatamaz ve takip modu `document_and_video` olmak **zorundadır** (§6.10). Aksi halde video yalnızca "geldi mi?" diye sayılır, hasar ve sayım ayrışması hiç değerlendirilmezdi. Karar motoru video sinyalini advisory ve sözleşmesel kanıt için **aynı biçimde** okur.

**Uygulama durumu (2026-07-09):** `RoboflowVideoAnalyzer`, uzantıya göre (`.mp4`/`.mov`/vb. → video, aksi → görsel) tek `analyze()` girişinden dispatch eder. İki Roboflow-hosted YOLOv8 modeli kullanılır (`inference-sdk` Python 3.13'ü henüz desteklemediği için resmi SDK yerine düz `requests` REST çağrısı, `roboflow_client.py`):

- **`logistics-sz9jr/2`** — koli (`cardboard box`) ve palet (`wood pallet`) sayımı. Ayrı bir palet-özel model (`pallet-detection-ith6b`) denendi, gerçek fotoğraflarla test edilince bırakıldı: istiflenmiş paletlerde tüm görseli kaplayan tek bir kutu döndürdü (5 ayrık paletlik kolay bir fotoğrafta bile 5/5 yerine 1) — palet sayımı bu modelde kalıyor.
- **`detecting-a-damaged-parcel/11`** — hasar sinyali: `hole`/`wet`/`screw` sınıfları. `correlator.py`, hasar tespitini merkez-noktası bir koli kutusunun içine düşüyorsa o koliye bağlar (`matched_box=true`); düşmüyorsa sinyal atılmaz, `matched_box=false` ile saklanır (koli tespit edilemese bile hasar riski kaybolmasın diye).

**Bilinen sınırlar (7 gerçek fotoğrafla doğrulandı):** ayrık/sınırları belirgin koli ve paletlerde sayım güvenilir (%86-96 confidence, testte 3/3, 24/24, 5/5, 10/10 doğru); **üst üste istiflenmiş** paletlerde ciddi eksik sayım (7 gerçek palet → 3 tespit); hasar modeli koli/parsel olmayan sahnelerde düşük-confidence yanlış pozitif üretebilir. Bu yüzden video sayımı tek başına otomatik onay tetiklememeli — e-irsaliye ile çapraz kontrol ve gerekirse insan onayı şart (bkz. §6.1).

**Kapsam dışı (bilinçli):** ayrı ayrı yüklenen birden fazla video/fotoğrafın (örn. aynı teslimatın iki videosu) toplanması `analyze()` seviyesinde yapılmaz — her çağrı tek bir medya dosyasını analiz eder. Bunun üst katmanda nasıl ele alınacağı (naif toplama aynı kolilerin iki kez gösterilip sayı şişirilmesine açıktır) henüz karara bağlanmadı.

### 3.5 Dış LLM'e giden içeriğin sınırlandırılması

`privacy.py`, markdown dönüşümünden sonra kişisel/hassas alanları (TCKN/vergi no, IBAN, telefon, adres…) tespit edip maskeler; maskeleme haritası lokalde kalır. Regülatif dayanak: TCMB Tebliğ md.9/21, Yönetmelik md.21(7)/62 (bkz. `plans/ready/regulasyon_rag_genisletmesi.md`).

**Uygulama durumu (2026-07-08):** `privacy.py` **minimal** implement edildi — regex tabanlı PII: TCKN (11 hane), VKN (10 hane), IBAN (`TR`+24, boşluk/tire ayraçlı formlar dahil), telefon, e-posta. `mask(text) → (masked_text, mapping)` + recursive `restore(obj, mapping)` (LLM çıktısındaki placeholder'lar lokalde orijinaline döndürülür). Kapsam bilinçli olarak dar: isim/adres gibi bağlam-bağımlı alanların NER'i ve bare-local telefon/VKN ayrımı sonraya bırakıldı. CLI hattında (`scripts/extract_contract.py`) mask, canlı LLM çağrısından **önce** çalışır (§6.7 sırası garanti).

**Kart-verisi güvenlik katmanı (2026-07-09):** `mask()/restore()` üstüne `analyze(text) → PrivacyReport(masked_text, mapping, detected_types, blocking_findings, risk_flags)` eklendi. Sıra kritiktir: önce standart `mask()`, sonra kart verisi taranır (IBAN'ın gruplu hanelerinin PAN sanılmasını önlemek için). Tespit: **PAN** (13-19 hane + Luhn doğrulaması → maskelenir, placeholder `mapping`'e **girmez** = restore edilmez, `PAN_DETECTED` risk flag), **CVV/CVC · track data · PIN** (bağlam-duyarlı → **SAD**, `blocking_findings`), PAN+expiry → `CHD_CONTEXT`. `blocking_findings` doluysa ve provider `openai` ise CLI **canlı çağrıyı atlar** → tip-tutarlı `ExtractionResult(status="needs_review", data=None, reason=…)` (sahte JSON üretilmez); fake provider (dışarı veri gitmez) çalışabilir ama sonuç `needs_manual_review=true` ile işaretlenir. `risk_flags`, restore sonrası extraction JSON'ın `risk_flags` alanına birleşir (şema donuk kalır). Kaynak: `plans/done/rag_context_builder_ve_guvenlik_katmani.md`.

### 3.6 Bildirim — `NotificationProvider` (Plan 03)

```python
NotificationProvider.send_invitation(to_email, transaction_id, invite_link) -> None
```

Adapter + fake ilkesi (§6.3): bu fazda yalnızca `FakeNotificationProvider` mevcuttur (ağa çıkmaz, link'i döndürür/loglar). Gönderim başarısız olsa bile (`NotificationDeliveryError`) invitation satırı ve audit kaydı commit'e gider — bildirim kanalı, business mutation'ı belirsiz bırakmaz (`CreatedInvitation.notification_delivered=False` ile işaretlenir).

## 4. API contract

### 4.1 REST endpoint'leri

| Endpoint | İş |
|---|---|
| `POST /api/transactions` | **Dual-mode (Plan 03, additive):** `acting_entity_id`+`own_role` yoksa anonim `legacy_v1` akışı (değişmedi) → `{id, buyer_link, seller_link, manager_link}`; verilmişse authenticated `account_v2` akışı (session + CSRF zorunlu, capability token YOK) → `{id, lifecycle_version, own_role, acting_entity_id, invitation}` |
| `GET /api/transactions` | Authenticated user yalnız aktif assignment'ı olduğu işlemleri görür; anonim istek yalnız `DEMO_PUBLIC_DASHBOARD=true` iken (legacy demo listesi) tüm işlemleri görür, aksi hâlde 403 |
| `GET /api/transactions/{id}` | Detay: extraction (redacted), validator raporu, event timeline, ödeme durumu, `lifecycle_version`, `canonical_state` (§2.8 projeksiyonu, yalnız `legacy_v1`). `account_v2` satırlar authenticated + assignment'lı erişim ister (401/403); `legacy_v1` açık kalır |
| `GET /api/transactions/{id}/party-view?token=…` | Taraf perspektifi (token → party çözümü) + `tracking_summary` — legacy_v1, `LEGACY_CAPABILITY_ACCESS_ENABLED` arkasında |
| `GET /api/transactions/{id}/manager-view?token=…` | Yönetici görünümü: sistem önerisi + reason code'lar, policy durumu, sözleşmesel kanıt şartları; **manager token** gerekir, taraf token'ı → 403 — legacy_v1, `LEGACY_CAPABILITY_ACCESS_ENABLED` arkasında |
| `PUT /api/transactions/{id}/tracking-policy` | Body `{manager_token, physical_delivery_confirmed, tracking_mode}` — taslak policy'yi günceller (idempotent) |
| `POST /api/transactions/{id}/tracking-policy/lock` | Body `{manager_token}` — policy'yi onaylardan önce kilitler (idempotent) |
| `POST /api/transactions/{id}/approvals` | Body `{token}` — token sahibi tarafın onayı; yanlış token → 403; **policy kilitli değilse → 409** |
| `POST /api/transactions/{id}/events/e-irsaliye?token=…` | E-irsaliye simülasyonu (demo butonu); seller veya manager capability token zorunlu (aksi 403), kanal etkin değilse → 409, `LEGACY_CAPABILITY_ACCESS_ENABLED=false` → 403 |
| `POST /api/transactions/{id}/delivery-video?token=…` | Video upload → inline analiz; seller veya manager capability token zorunlu (aksi 403), kanal etkin değilse → 409, `LEGACY_CAPABILITY_ACCESS_ENABLED=false` → 403 |
| `GET /api/transactions/{id}/evidence?token=…` | Kanıt paketi (JSON bundle, tracking policy snapshot'ı dahil); buyer/seller/manager token'larından biri zorunlu, aksi hâlde **403** |

**Policy/delivery 409 gövdesi** her zaman `detail: {code, message, conflicts[]}` şeklindedir. Kodlar: `POLICY_NOT_CONFIGURABLE` (validator PASS değil veya state `awaiting_approval` değil) · `POLICY_LOCKED` · `POLICY_INVALID` · `POLICY_CONTRACT_CONFLICT` · `POLICY_NOT_LOCKED` (onay öncesi) · `TRACKING_NOT_ENABLED` · `TRANSACTION_DECIDED`.

**Kanıt kanalı guard'ı (`delivery.py`):** e-irsaliye yalnızca sözleşme onu şart koşuyorsa **veya** policy `document_only|document_and_video` ise kabul edilir; video yalnızca sözleşmesel video şartı varsa **veya** policy `document_and_video` ise kabul edilir. Karara bağlanmış (`decided`) işleme geç gelen kanıt, herhangi bir video analizi yapılmadan `TRANSACTION_DECIDED` ile reddedilir.

**Public cevaplarda redaksiyon:** detay, party/manager view ve evidence bundle `services/extraction_projection.py` üzerinden geçer — `tax_id`, capability token'ları ve ham markdown hiçbirinde bulunmaz.

`source_quote` yalnızca **capability token'ı gerektiren** uçlarda döner (party-view · manager-view · evidence) ve orada da `privacy.analyze()` ile maskelenir: taraf, onaylayacağı kuralın sözleşmedeki dayanağını görebilmelidir (§6.2). Token istemeyen `GET /api/transactions/{id}` ve liste ucu alıntıyı **döndürmez** — maskeleme desen tabanlıdır (TCKN/VKN/IBAN/telefon/e-posta/kart), NER değildir; alıntıdaki kişi adı, adres veya ticari hassas ifade temizlenmez. `redacted_extraction_projection(..., include_source_quote=False)` varsayılanı bu yüzden kapalıdır. Ham alıntı yalnız DB'de kalır.

### 4.1.1 Identity/entity/participant/invitation endpoint'leri (Plan 03)

| Endpoint | İş |
|---|---|
| `POST /api/auth/register` | Kayıt (Argon2id parola hash) → `UserPublic` |
| `POST /api/auth/login` | Giriş → session + CSRF cookie set edilir (`m4t_session` HttpOnly, `m4t_csrf` JS-okunabilir) |
| `POST /api/auth/logout` | Mevcut session'ı revoke eder, cookie'leri temizler (CSRF zorunlu) |
| `GET /api/auth/me` | Mevcut authenticated user (`UserPublic`) |
| `POST /api/auth/sessions/revoke` | User'ın TÜM aktif session'larını revoke eder (CSRF zorunlu) |
| `POST /api/entities` | Legal entity oluşturur, oluşturan otomatik `owner` membership alır |
| `GET /api/entities` · `GET /api/entities/{id}` · `PATCH /api/entities/{id}` | Yalnız aktif membership sahibi görür/günceller (member salt-okunur); ciphertext/HMAC hiçbir response'a girmez |
| `POST /api/transactions/{id}/invitations` | CSRF zorunlu; yalnız transaction manager/creator. Bağlanmış role yeni davet reddedilir; yeni davet aynı role ait eski pending daveti revoke/supersede eder. |
| `GET /api/invitations/{token}/preview` | Auth'suz, PII'siz güvenli önizleme |
| `POST /api/invitations/{token}/accept` | CSRF zorunlu; authenticated user, email eşleşmesi zorunlu, creator kendi davetini kabul edemez; participant yalnız unbound+invited ise atomik bağlanır. |
| `POST /api/transactions/{id}/invitations/{invitation_id}/revoke` | CSRF zorunlu; yalnız manager/creator |
| `GET /api/transactions/{id}/participants` | Transaction access sahibi (assignment) |
| `PUT .../participants/me/profile` · `POST .../participants/me/confirm` | CSRF zorunlu; declared → confirmed snapshot; confirmed sonrası kilitlenir |
| `GET /api/transactions/{id}/reviews` | Transaction assignment sahibi veya platform reviewer/admin için review case + action listesi; GET side-effect üretmez |
| `POST /api/reviews/{review_case_id}/actions` | CSRF zorunlu; comment transaction manager/approver veya platform reviewer/admin, state-changing action yalnız platform reviewer/admin; blocking case `resolve_continue` ile bypass edilemez |

**Session/CSRF:** cookie `HttpOnly` + `SameSite=Lax` (+ prod'da `Secure`, `SESSION_COOKIE_SECURE`); mutating uçlarda `X-CSRF-Token` header zorunlu (sabit-zamanlı karşılaştırma) + verilmişse `Origin` host eşleşmesi. Session/CSRF raw token'ları DB'de yalnız SHA-256 hash. `X-Acting-Entity-ID` header'ı yalnız gerçek aktif membership doğrulanırsa `ActorContext.acting_entity_id`'yi doldurur.

### 4.2 Extraction JSON şeması — **ikili sözleşme noktası**

`schemas/extraction.py` (Pydantic) tek doğruluk kaynağıdır; fake ve gerçek extraction aynı şemayı döndürür. Değişiklik ekip mutabakatı gerektirir.

> Şema **sözleşmenin ne söylediğini** temsil eder; platformun operasyonel takip tercihi buraya yazılmaz (o `schemas/tracking.py`de yaşar). `trigger.delivery_video` ve `required_evidence.video` yalnızca sözleşme videoyu açıkça şart koştuğunda kullanılır. Alan adları ve enum üyeleri `tests/test_extraction_schema.py`deki yapısal snapshot testiyle kilitlidir.

`extraction_runs.extraction_json` adapter'ın restore öncesi typed payload'ını immutable saklar; `rule_set_versions.rules_json` ise restore edilmiş ve aynı `ExtractionJSON` şemasıyla doğrulanmış kanonik payload'dır. Bu ayrım şemayı genişletmez.

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

Event tipleri: `contract_extracted` · `rules_validated` · `tracking_policy_recommended` · `tracking_policy_updated` · `tracking_policy_locked` · `buyer_approved` · `seller_approved` · `e_irsaliye_received` · `delivery_video_analyzed` · `payment_decision_created` · `mock_payment_executed` · `dispute_opened`

`payment_decision_created` payload'ı `action` · `capture_ratio` · `rationale` · `findings[{code, severity, message}]` · `manual_review_required` taşır. `dispute_opened` yalnızca gerçek (insan kararlı) dispute içindir — **opsiyonel video anomalisi bu event'i üretmez**, `action=hold` + `manual_review_required=true` üretir.

Event payload'larında capability token (`manager_token`/`buyer_token`/`seller_token`), ham markdown, maskeleme haritası ve kart verisi **bulunmaz**.

## 5. Veri modeli ve state machine

Tablolar (baseline): `transactions` (state, buyer_token, seller_token, **manager_token**, markdown, + Plan 03: `created_by_user_id`, `owner_entity_id`, `lifecycle_version`, `content_sha256`) · `extracted_rules` (extraction_json, validator_status, validator_report) · **`tracking_policies`** · `approvals` · `events` · `mock_payments` · `evidence`

`tracking_policies` (transaction başına en fazla bir satır, `transaction_id` PK): `recommendation` (`yes|no|uncertain`, sistem önerisi) · `recommendation_reason_codes` (JSON, güvenli kod listesi — sözleşme metni taşımaz) · `manager_physical_delivery_confirmed` (`null` iken kilitlenemez) · `tracking_mode` (`off|document_only|document_and_video`) · `video_role` (sabit `advisory`) · `status` (`draft|locked`) · `configured_at` · `locked_at`.

### 5.1 Identity/entity/participant tabloları (Plan 03)

- `users` (`UNIQUE(email_normalized)`) · `sessions` (`UNIQUE(token_hash)`, `FK user_id ON DELETE CASCADE`, `last_seen_at` throttled) — parola/session (§4.1.1).
- `legal_entities` (`tax_identifier_ciphertext` AES-256-GCM, `tax_identifier_lookup_hmac` deterministik HMAC-SHA256, `tax_identifier_last4`) · `memberships` (`UNIQUE(user_id, legal_entity_id)`, `role: owner|admin|member`).
- `transaction_participants` (`role: buyer|seller`, extracted/declared/confirmed snapshot) · `transaction_assignments` (`role: manager|approver|viewer`, list/detail scoping bunun üzerinden yapılır) · `transaction_invitations` (token yalnız hash'lenmiş saklanır, expiry, tek kullanım; aynı role tek canlı pending davet; accept participant'ı compare-and-set ile bağlar).
- `audit_events` — actor/entity/request_id + allowlist'li metadata; business mutation ile **aynı connection/transaction'da** yazılır (`services/audit.py::record`), kendi commit/rollback yapmaz.

### 5.2 `lifecycle_version` — iki paralel akış (v2 §2.8, additive)

`transactions.lifecycle_version` (`legacy_v1` | `account_v2`, `NOT NULL DEFAULT 'legacy_v1'`):

- **`legacy_v1`**: anonim capability-link akışı, **hiç değişmedi**. `GET .../{id}` açık kalır; party/manager-view/delivery `LEGACY_CAPABILITY_ACCESS_ENABLED` (varsayılan `true`, Wave 3'e kadar) arkasında token ile çalışır. Detay cevabında `canonical_state` (aşağıda) doldurulur.
- **`account_v2`**: `POST /api/transactions`'a `acting_entity_id`+`own_role` verildiğinde authenticated akış — capability token **üretilmez**; erişim `transaction_assignments` üzerinden scoped'dur (list/detail 401/403). Kendi state machine'i henüz tanımlı değil (Plan 03+ kapsamı dışı); `canonical_state` bu satırlarda `None`.

`ParticipantService` (frozen, v2 §8.1, `services/participants.py`): `attach_creator` (işlemi başlatan actor'ı `own_role` participant'ı yapar + manager assignment açar) · `create_counterparty_placeholder` (karşı taraf için `invited` durumunda placeholder, idempotent) · `accept_invitation` (email eşleşmesi zorunlu, creator kendi davetini kabul edemez, aynı legal entity iki taraf olamaz).

### 5.3 Legacy state canonical projeksiyonu (v2 §2.8)

`services/transaction_state.py` (saf, DB-bağımsız), yalnız `legacy_v1` satırları canonical görünüme çevirir:

| Legacy state | Canonical görünüm |
|---|---|
| uploaded / extracting | processing |
| awaiting_review | preparation / blocked_review (Program 1'de her zaman blocking) |
| awaiting_approval | preparation / ready_for_ratification (policy `locked` mı?) |
| rejected | rejected |
| active | active |
| evidence_pending | active / blocked_evidence (son `payment_decision_created.manual_review_required`) |
| decided | settled / partially_settled (`mock_payments.status`) |

**Migration:** `init_db()` versiyonlu migration runner'a delegedir. Sıra: `001_baseline_current_schema` (sekiz legacy runtime tablosu) → `003_identity_sessions` → `004_legal_entities_memberships` → `005_participants_invitations` → `006_audit_events` → `007_transaction_lifecycle_v2` → `008_documents_extraction_runs` → `009_rule_set_versions` → `010_review_cases`. `007`, `transactions`'a additive kolonlar ekler ve mevcut satırları `legacy_v1` backfill eder. `008`, `contract_documents` + immutable `extraction_runs`; `009`, immutable-content `rule_set_versions`; `010`, `review_cases` + append-only `review_actions` tablolarını ekler. `002` kasıtlı olarak rezerve/kullanılmamıştır. Boş DB tüm pending migration'ları atomik uygular; `schema_migrations` bulunmayan mevcut DB ancak tablo+kolon fingerprint'i tam eşleşirse `001` olarak stamp edilir, sonraki migration'lar normal döngüyle eklenir. Kısmi/bilinmeyen legacy şema `UnknownLegacySchemaError` ile **hiç mutate edilmeden** reddedilir. Migration SQL'i ile applied marker aynı transaction'dadır; kesinti rollback olur ve rerun güvenlidir. Her request bağlantısı başarıda commit, hatada açık rollback ve her durumda close uygular; background task kendi bağlantısını açar. Bağlantılar `timeout=5.0`, `busy_timeout=5000`, WAL, foreign key ve `sqlite3.Row` ayarlarını korur.

```
uploaded → extracting → awaiting_review | awaiting_approval | rejected
                          + policy.status = draft
policy locked  (yalnız validator PASS ∧ state=awaiting_approval)
        → taraf onayları açılır
iki onay → pool payment + active
        → harici efektif kanıt yoksa: settlement → decided (capture)
        → kanıt bekleniyorsa: evidence_pending
kanıt yeterli ve temiz → decided
video anomalisi / manuel inceleme → evidence_pending'de kalır (release yok)

validator REJECT → rejected (akış durur; policy yapılandırılamaz)
```

Policy yaşam döngüsü transaction state'inden **ayrıdır**: UI "takip politikası bekleniyor" durumunu `policy.status`'ten türetir, yeni transaction state'i eklenmez. `hold` sonucunda transaction `decided` yapılmaz.

Karar → ödeme aksiyonu: tam teslim `capture` · kısmi `partial_capture` (oran yalnız birincil kanıttan) · eksik/şüpheli kanıt `hold` (capture çağrılmaz, evidence snapshot alınır). `dispute` literal'i geriye uyumluluk için `DecisionResult`ta durur; opsiyonel video onu üretmez.

## 6. Dışına çıkılmayacak tasarım kalıpları

1. **LLM para yolunda değildir.** LLM önerir → validator (deterministik) denetler → insanlar onaylar → motor uygular. Release endpoint'ini yalnızca deterministik motor çağırır.
2. **Validator kapısı atlanamaz.** LLM çıktısı PASS almadan aktif kural olmaz; NEEDS_REVIEW insan ister; REJECT akışı durdurur. UI her zaman gerekçeyi gösterir.
3. **Her dış bağımlılık adapter + fake çifti olarak yazılır** ve env ile seçilir (LLM, ödeme, video). Fake'ler demo fallback'idir.
4. **Event bus = events tablosu.** Ayrı mesajlaşma altyapısı kurulmaz; kanıt zinciri bu tablodan üretilir.
5. **Decision engine saf fonksiyondur** — I/O yapmaz, girdi/çıktısı test edilebilir. DB/event/ödeme orkestrasyonu `services/settlement.py`'de yaşar; release guard **tek yerdedir** ve router'lar birbirinin private fonksiyonlarını import etmez.
6. **Taraf kimliği = token (yalnız `legacy_v1` — Plan 03 ile legacy geçiş aracına indirgendi).** Capability URL modeli anonim/legacy akışta yaşamaya devam eder; yönetici de bir capability token'ıdır (`secrets.token_urlsafe(32)`), token'lar log/event/evidence'a girmez, yanlış rol token'ı endpoint bazında 403 alır. `account_v2` akışında kimlik artık session-cookie + `users`/`memberships`/`transaction_assignments`'tır — capability token üretilmez (§5.1-5.2, v2 §2.2). İki model additive olarak bir arada yaşar; legacy'nin kaldırılması Wave 3 hard cutover'a kadar yapılmaz.
7. **Local-first.** Runtime'daki tek dış çağrı LLM API'sidir; o da yalnızca maskelenmiş içerik alır.
8. **Gerçek para hareketi ve gerçek kart verisi yoktur** (demo). Prod anlatısı: lisanslı altyapının (Moka havuz/cüzdan) üstünde karar-kanıt katmanı.
9. **Video tek başına para hareketi üretemez.** Opsiyonel (platform) videosu advisory'dir: teslim miktarını, kısmi ödeme oranını, release'i veya dispute'u belirleyemez; en fazla `hold` + manuel inceleme tetikler (§3.4).
10. **Sözleşmesel kanıt platform tercihini yener.** Extraction'daki `required_evidence` yönetici policy'siyle devre dışı bırakılamaz **veya zayıflatılamaz**; sözleşmesel video `tracking_mode=document_and_video` zorunlu kılar. Çelişkide policy kilidi 409 ile reddedilir. LLM/RAG takip politikasını **seçmez** — politika `ExtractionJSON` içine yazılmaz.
11. **Takip politikası taraf onaylarından önce kilitlenir** ve iki tarafa da gösterilir. Kilitlenmemiş policy'de onay 409'dur; kilit sonrası policy değişmez (amendment akışı kapsam dışı — yeni transaction açılır).
12. **Audit event, business mutation ile aynı connection/transaction'da yazılır** (`services/audit.py::record`); kendi commit/rollback/close yapmaz — business mutation rollback olursa audit satırı da rollback olur. Metadata serbest metin değildir; yalnız scalar enum/ID/status değerleri kabul edilir, token/secret/ham PII güvenli anahtar altında da reddedilir.
13. **`ParticipantService` (v2 §8.1) donmuş bir arayüzdür** — `attach_creator`/`create_counterparty_placeholder`/`accept_invitation` idempotenttir; aynı legal entity aynı işlemde iki taraf olamaz, creator kendi davetini kabul edemez. Accept yalnız `legal_entity_id IS NULL ∧ status=invited ∧ confirmed_at IS NULL` participant'ı atomik bağlar; mevcut ownership/confirmed snapshot ezilemez.
14. **Session-authenticated mutation CSRF korumalıdır.** Account transaction create, entity, invitation ve participant mutation'ları `X-CSRF-Token` doğrular; verilmiş `Origin` request host ile eşleşmelidir. Anonim `legacy_v1` upload etkilenmez.
