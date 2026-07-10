# Backend İskeleti ve İşlem Akışı (FastAPI + Validator + Onay + Mock Ödeme)

> **Durum:** Uygulandı — 2026-07-09 · 5 fazda (commit'ler faz 1-5). Suite 91→149 test yeşil. Dört demo senaryosu (tam teslim→capture, kısmi→partial, çelişki→dispute, bozuk sözleşme→REJECT "altın an") TestClient'ta uçtan uca geçer.
> **Sapmalar:** (1) `document_parser` `code/scripts/` altında kaldı; backend `sys.path` köprüsüyle import eder (ARCHITECTURE §1 `services/documents/` öngörür — relokasyon ertelendi, §1'e not düşüldü). (2) Fake fixture `required_evidence` birleşimi `{contract,e_irsaliye,video}` olduğundan tam capture için hem e-irsaliye hem video gönderilmeli (kod değil, fixture davranışı). (3) Faz 4 mekanik testleri `tests/test_delivery_flow.py`'de; `tests/test_api_flow.py` dört demo senaryosu + REJECT'i taşır (test dosyası bölünmesi). (4) Validator yüzde toplamı `round(...,2)` ile karşılaştırılır (kayan nokta sınır hatası). (5) Bu FastAPI sürümünde lifespan/`init_db` yalnızca `with TestClient(app) as c:` ile tetiklenir — API testleri bağlam yöneticisi kullanır.

> **Tür:** Uygulama planı (uygulandı).
> **Kaynak:** 09.07.2026 planlama oturumu; ARCHITECTURE §1/§3.3/§3.4/§4/§5/§6 birebir uygulanır.
> **Devralınan kalemler:** validator hassas-veri kontrolleri — [regulasyon_rag_genisletmesi](regulasyon_rag_genisletmesi.md) ve [rag_context_builder_ve_guvenlik_katmani](../done/rag_context_builder_ve_guvenlik_katmani.md) planlarından iki kez devredildi, sahibi bu plandır.

## Status

done

## Goal

Demo senaryolarının tamamını API üzerinden uçtan uca çalıştırabilen FastAPI servisini kurmak: sözleşme upload → extraction pipeline (mevcut servisler) → **deterministik validator** → token'lı çift taraf onayı → mock havuz ödemesi → teslimat kanıtları → **decision engine** → ödeme aksiyonu + evidence bundle. Bu plan bittiğinde YOL_HARITASI §3'teki dört demo senaryosu curl/test seviyesinde oynatılabilir olmalı; frontend yalnızca bu API'yi tüketecek.

## Background

- Extraction hattı hazır ve testli (91 test): `convert → analyze → ContextBuilder → extract → restore` zinciri `scripts/extract_contract.py`'de CLI olarak çalışıyor; backend aynı servisleri (`document_parser`, `privacy.analyze`, `ContextBuilder`, `ExtractionService`) doğrudan kullanacak.
- `backend/app/` altında yalnızca `config.py`, `schemas/extraction.py`, `services/{rag,privacy,extraction,context_builder}.py` var. **`main.py`, `db.py`, `eventbus.py`, `routers/`, `validator.py`, `decision.py`, `payment_provider.py`, `video.py`, `evidence.py` yok.**
- `requirements.txt`'te FastAPI/uvicorn yok; test bağımlılıkları arasında httpx yok.
- Moka mock contract'ı [moka_cüzdan_entegrasyonu](../planning/moka_cüzdan_entegrasyonu.md)'nda araştırılmış: `IsPoolPayment=1`, `DoApprovePoolPayment`, response şekli `ResultCode: "Success"` + `Data.IsSuccessful` + `Data.VirtualPosOrderId`, bizim `transaction_id` → `OtherTrxCode`. Mentor cevabı beklemede ama mock public havuz contract'ına göre yazılacağı için **bloklamıyor**.
- Validator'a iki plandan devredilen kontroller: "extraction çıktısında maskelenmemiş hassas alan → NEEDS_REVIEW" ve "kart placeholder (`[[CARD_*]]`) sızıntısı → REJECT".

## Problem

Ürünün iddiası "LLM önerir → validator denetler → insanlar onaylar → deterministik motor uygular" zinciri; şu an bu zincirin yalnızca ilk halkası (LLM önerisi) çalışıyor. Validator, onay akışı, ödeme simülasyonu ve kanıt zinciri olmadan ne demo senaryoları ne de "altın an" (bozuk sözleşme → REJECT) gösterilebilir. Frontend de başlayamıyor çünkü tüketeceği API yok.

## Non-goals

- **Frontend yok** — ayrı plan; bu plan yalnızca API'yi teslim eder.
- **Gerçek Moka çağrısı yok** (`RealMokaProvider` v1 işi); gerçek video detector yok (`FakeVideoAnalyzer` yeterli, YOL_HARITASI §4 araştırması ayrı iş).
- Auth/users tablosu yok — taraf kimliği token'dır (§6.6); token dışında yetkilendirme kurulmaz.
- ORM/migration altyapısı yok — stdlib `sqlite3`, şema `init_db()` ile kurulur.
- Queue/websocket yok — arka plan işleri `BackgroundTasks` (§2).
- §4.2 extraction şemasına ve mevcut extraction/privacy/context_builder servislerinin davranışına dokunulmaz.
- E-irsaliye gerçek entegrasyonu yok — demo butonu simülasyonu (§4.1).

## Proposed design

### Modüller (ARCHITECTURE §1 dizinine birebir)

```text
backend/app/
├── main.py            # FastAPI app factory + router include + startup'ta init_db
├── db.py              # sqlite3: connect (per-request dependency, WAL) + init_db (6 tablo, §5)
├── eventbus.py        # emit(conn, transaction_id, event_type, payload, source) → events tablosu (§4.3/§6.4)
├── routers/
│   ├── transactions.py  # POST/GET /api/transactions, GET detay, GET party-view, upload pipeline'ı
│   ├── approvals.py     # POST /api/transactions/{id}/approvals
│   ├── delivery.py      # POST .../events/e-irsaliye, POST .../delivery-video
│   └── evidence.py      # GET .../evidence
└── services/
    ├── validator.py         # deterministik kural kapısı (saf fonksiyon)
    ├── decision.py          # decision engine (saf fonksiyon, I/O yok — §6.5)
    ├── payment_provider.py  # PaymentProvider ABC + MockMokaProvider (§3.3)
    ├── video.py             # VideoAnalyzer ABC + FakeVideoAnalyzer (§3.4)
    └── evidence.py          # events + rapor + onay + ödeme kayıtlarından zaman damgalı JSON bundle
```

### Veri modeli (§5 tabloları, pinlenmiş kolonlar)

```sql
transactions(id TEXT PK, state TEXT, buyer_token TEXT, seller_token TEXT,
             markdown TEXT, masked_markdown TEXT, created_at TEXT)
extracted_rules(transaction_id TEXT, extraction_json TEXT, validator_status TEXT,
                validator_report TEXT, created_at TEXT)
approvals(transaction_id TEXT, party TEXT, created_at TEXT)          -- party: buyer|seller
events(id INTEGER PK, transaction_id TEXT, event_type TEXT,
       payload TEXT, source TEXT, created_at TEXT)                    -- §4.3 zarfı
mock_payments(transaction_id TEXT, other_trx_code TEXT, virtual_pos_order_id TEXT,
              status TEXT, amount REAL, created_at TEXT)
evidence(transaction_id TEXT, bundle_json TEXT, created_at TEXT)
```

Privacy sınırı: ham `markdown` yalnızca lokal DB'de kalır (local-first, §6.7); `events`, `evidence` ve API cevaplarındaki sözleşme içeriği **maskeli** halden üretilir. Maskeleme haritası **persist edilmez** (pipeline task'ının belleğinde yaşar, restore orada yapılır).

### State machine (§5, geçiş tetikleri pinli)

```text
uploaded → extracting            : upload sonrası background task başlar
extracting → awaiting_review     : validator NEEDS_REVIEW
extracting → awaiting_approval   : validator PASS
extracting → rejected            : validator REJECT (akış durur, gerekçe kayıtlı)
awaiting_review → awaiting_approval yok — NEEDS_REVIEW'da taraf linkleri açıktır,
  uyarılar party-view'da gösterilir; İNSAN ONAYI review çözümüdür (§6.2):
  iki taraf da onaylarsa akış devam eder.
awaiting_review|awaiting_approval → active : buyer_approved ∧ seller_approved
  → PaymentProvider.create_pool_payment (IsPoolPayment=1) → state=active (funds_held)
active → evidence_pending        : ilk teslimat kanıtı event'i
evidence_pending → decided       : decision engine HOLD dışı karar verdiğinde
  (captured | partially_captured | disputed); HOLD → evidence_pending'de kalır
```

### Validator (`services/validator.py`)

```python
@dataclass(frozen=True)
class ValidatorFinding:
    code: str; severity: Literal["reject", "review"]; message: str

@dataclass(frozen=True)
class ValidatorReport:
    status: Literal["PASS", "NEEDS_REVIEW", "REJECT"]
    findings: list[ValidatorFinding]

def validate(extraction: ExtractionJSON, *, confidence_threshold: float = 0.7) -> ValidatorReport
```

Saf fonksiyon, I/O yok. Kontroller (severity ile pinli):

| Kontrol | Sonuç |
|---|---|
| `sum(percentage)` ≠ 100 (±0.01 tolerans) | **REJECT** — "altın an" senaryosunun kaynağı |
| `payment_rules` boş | **REJECT** |
| Herhangi bir string alanda `[[CARD_` placeholder'ı (sızıntı) | **REJECT** (devralınan kontrol) |
| Serialize edilmiş çıktıda maskelenmemiş PII (`privacy` desenleriyle tarama: TCKN/VKN/IBAN/telefon/e-posta/PAN) — `parties.*.tax_id` alanları **muaf** (şemanın meşru alanı) | NEEDS_REVIEW (devralınan kontrol) |
| Herhangi bir kuralda `confidence < threshold` | NEEDS_REVIEW |
| Herhangi bir kuralda `source_quote` boş/whitespace | NEEDS_REVIEW |
| `needs_manual_review == true` (LLM kendisi işaretlemiş) | NEEDS_REVIEW |
| `total_amount <= 0` | NEEDS_REVIEW |
| `risk_flags` içinde `CHD_CONTEXT`/`PAN_DETECTED`/security flag | NEEDS_REVIEW |

REJECT > NEEDS_REVIEW > PASS önceliğiyle tek status'e indirgenir; rapor her zaman gerekçeli findings taşır (§6.2 "UI her zaman gerekçeyi gösterir").

### Decision engine (`services/decision.py`)

```python
@dataclass(frozen=True)
class DeliveryEvidence:
    e_irsaliye: dict | None      # {"delivered_quantity": float, ...} (simülasyon payload'ı)
    video: dict | None           # VideoAnalyzer çıktısı: {"counts": int, "damage_signals": [...], "confidence": float}

@dataclass(frozen=True)
class DecisionResult:
    action: Literal["capture", "partial_capture", "hold", "dispute"]
    capture_ratio: float         # 0.0-1.0; capture=1.0, hold/dispute=0.0
    rationale: str               # Türkçe gerekçe (UI/evidence için)

def decide(extraction: ExtractionJSON, evidence: DeliveryEvidence) -> DecisionResult
```

Saf fonksiyon (§6.5). Karar sırası pinli:

1. Gerekli kanıt eksikse (kuralların `required_evidence` birleşimi karşılanmadıysa) → `hold`.
2. E-irsaliye ↔ video **çelişkisi** (her ikisi de varsa ve sayımlar sözleşme miktarına göre %10'dan fazla ayrışıyorsa, veya video `damage_signals` doluysa) → `dispute`.
3. Teslim edilen miktar < sözleşme miktarı → `partial_capture`, `capture_ratio = teslim/sözleşme` (0-1'e kıskaçlanır).
4. Aksi halde → `capture`.

Sözleşme miktarı = `commercial_terms.goods` quantity toplamı. Eşikler sabit (demo için yeterli); Settings'e taşınması opsiyonel iyileştirme.

### PaymentProvider (`services/payment_provider.py`, §3.3)

ABC metotları §3.3'teki beş imza. `MockMokaProvider` cevapları gerçek Moka şeklinde:

```python
{"ResultCode": "Success", "ResultMessage": "", 
 "Data": {"IsSuccessful": True, "VirtualPosOrderId": "ORDER-<uuid>", "ResultCode": "", "ResultMessage": ""}}
```

`create_pool_payment(amount, currency, other_trx_code)` → `mock_payments` kaydı (status=`pool`); `approve_pool_payment(other_trx_code)` → status=`released` (capture) — partial'da `amount * capture_ratio` release edilir, kalan `pool`'da işaretlenir; `refund_payment` → status=`refunded`. **Release çağrısını yalnızca deterministik akış yapar** ve yalnızca şu koşulda: `buyer_approved ∧ seller_approved ∧ decision.action ∈ {capture, partial_capture} ∧ state == active/evidence_pending` (§3.3/§6.1). `dispute` → capture gitmez, evidence snapshot alınır (§5). Seçim env: `PAYMENT_PROVIDER=mock` (Settings'e alan eklenir).

### Video (`services/video.py`, §3.4)

`VideoAnalyzer` ABC + `FakeVideoAnalyzer.analyze(path) → {"counts": N, "damage_signals": [], "confidence": 0.9}` — sayım değerleri dosya adından ipucuyla veya sabit fixture'dan (demo senaryolarını oynatabilmek için `hasarli`/`eksik` gibi dosya adı ipuçları kabul edilir; kural basit ve dokümante olmalı). Env: `VIDEO_ANALYZER=fake`. Analiz `BackgroundTasks`'ta koşar → `delivery_video_analyzed` event'i. Video tek başına ödeme kararı veremez (§3.4) — yalnızca `DeliveryEvidence.video` girdisidir.

### Evidence (`services/evidence.py`)

`build_bundle(conn, transaction_id) → dict`: işlem özeti (maskeli), extraction JSON, validator raporu, onaylar, tüm event zinciri (§6.4 "kanıt zinciri bu tablodan üretilir"), mock ödeme kayıtları, decision gerekçesi; her kayıtta timestamp. Ham PII/kart verisi ve maskeleme haritası bundle'a **giremez** (pci.req.10 kontrol haritasıyla tutarlı). `GET /api/transactions/{id}/evidence` bunu döndürür ve `evidence` tablosuna snapshot yazar.

### Router'lar (§4.1'in sekiz endpoint'i, ek yok)

- `POST /api/transactions` — multipart dosya (`pdf/docx/png/jpg` + test/demo kolaylığı için `md/txt` passthrough). Akış: kaydet → `transactions` satırı (uuid id, `secrets.token_urlsafe` ile buyer/seller token) → `{id, buyer_link, seller_link}` **hemen** döner → `BackgroundTasks` pipeline: convert → `privacy.analyze()` → ContextBuilder → extract → restore → `validate()` → `extracted_rules` + state geçişi + `contract_extracted`/`rules_validated` event'leri. Blocking finding'de canlı LLM atlanır (CLI ile aynı kural) → NEEDS_REVIEW yolu. Pipeline hatası → state `awaiting_review` + hata gerekçeli event (hat asla sessiz çökmez).
- `GET /api/transactions` — liste (id, state, taraf adları maskeli özet, created_at).
- `GET /api/transactions/{id}` — detay: extraction, validator raporu, event timeline, ödeme durumu (§4.1).
- `GET /api/transactions/{id}/party-view?token=…` — token → party çözümü; kural özeti + validator uyarıları; yanlış token → 403.
- `POST /api/transactions/{id}/approvals` — body `{token}`; token sahibi tarafın onayı, tekrar onay idempotent; yanlış token → 403. İki onay tamamlanınca `create_pool_payment` + state=active + event'ler.
- `POST /api/transactions/{id}/events/e-irsaliye` — demo simülasyonu, body `{delivered_quantity, ...}` → `e_irsaliye_received` event + decision denemesi.
- `POST /api/transactions/{id}/delivery-video` — upload → background analiz → `delivery_video_analyzed` event + decision denemesi.
- `GET /api/transactions/{id}/evidence` — bundle JSON.

Her kanıt event'i sonrası **decision denemesi**: `decide()` çağrılır; `hold` → durum değişmez; diğer aksiyonlar → `payment_decision_created` + ödeme aksiyonu + `mock_payment_executed` (veya `dispute_opened`) event'leri + state=decided.

### Config/env ekleri

`Settings`'e: `payment_provider: str = "mock"` (env `PAYMENT_PROVIDER`), `video_analyzer: str = "fake"` (env `VIDEO_ANALYZER`), `db_path: Path` (env `DB_PATH`, default `code/data/runtime/m4trust.db` — dizin gitignore'a eklenir), `validator_confidence_threshold: float = 0.7` (env `VALIDATOR_CONFIDENCE_THRESHOLD`). `.env.example` güncellenir — **eksik kalmış `RAG_SECURITY_COLLECTION` satırı da eklenir** (önceki planın küçük dokümantasyon açığı).

### Bağımlılıklar

`requirements.txt`'e: `fastapi`, `uvicorn[standard]`, `python-multipart` (upload), `httpx` (TestClient için, tests bölümüne). SQLite stdlib — yeni DB bağımlılığı yok.

## Files likely involved

- **Yeni:** `backend/app/main.py`, `db.py`, `eventbus.py`, `routers/{__init__,transactions,approvals,delivery,evidence}.py`, `services/{validator,decision,payment_provider,video,evidence}.py`
- **Değişen:** `backend/app/config.py` (yeni alanlar), `backend/.env.example`, `code/requirements.txt`, `.gitignore` (`code/data/runtime/`)
- **Yeni testler:** `tests/test_validator.py`, `tests/test_decision.py`, `tests/test_payment_provider.py`, `tests/test_api_flow.py` (TestClient uçtan uca + 4 demo senaryosu)
- **Doc-sync:** `ARCHITECTURE.md` (§2 stack bağımlılık satırı; §4.1/§5 sapma olursa), `AGENTS.md` (pratik notlar: backend çalıştırma komutu)

## Implementation steps

Önerilen commit sınırları: (1) adım 1-2 "app iskeleti + DB + eventbus", (2) adım 3 "validator", (3) adım 4-5 "upload pipeline + onay + mock ödeme", (4) adım 6-7 "kanıt + karar + evidence", (5) adım 8 doc-sync.

1. Bağımlılıklar + `main.py` (app factory, startup'ta `init_db`) + `db.py` (WAL, per-request connection dependency) + `eventbus.py`. Boş app `uvicorn` ile kalkar, `/docs` açılır.
2. `config.py` yeni alanlar + `.env.example` + `.gitignore`.
3. `services/validator.py` + `tests/test_validator.py` — yukarıdaki kontrol tablosunun tamamı, devralınan iki kontrol dahil; sınır durumları (99.99/100.01 tolerans, boş kural listesi, tax_id muafiyeti) testli. **Bu adım tek başına kararlı nokta** (saf fonksiyon, API'siz test edilir).
4. `routers/transactions.py`: upload + background pipeline (CLI'daki akışın servis çağrılarıyla yeniden kullanımı — `extract_contract.py`'den kopya değil, aynı servislerin çağrımı) + liste/detay/party-view + state geçişleri + event'ler. Fake provider ile TestClient'ta upload→extraction→validation zinciri yeşil.
5. `routers/approvals.py` + `services/payment_provider.py`: çift onay → `create_pool_payment` → active. Yanlış token 403, idempotent onay, tek onayda ödeme oluşmadığı testli.
6. `routers/delivery.py` + `services/video.py` + `services/decision.py` + `tests/test_decision.py`: e-irsaliye simülasyonu, video upload+fake analiz, her kanıt sonrası decision denemesi, karar → ödeme aksiyonu (release/partial/dispute) + event'ler.
7. `services/evidence.py` + `routers/evidence.py`: bundle üretimi; bundle'da ham PII/kart verisi olmadığı testli.
8. `tests/test_api_flow.py`: **dört demo senaryosu** uçtan uca (tam teslim → capture; kısmi → partial_capture; çelişkili → dispute + ödeme kilitli; bozuk sözleşme [%40+%50] → REJECT + gerekçe). REJECT senaryosu için teste özel enjekte edilen fake extraction varyantı kullanılır. Doc-sync + plan durum bloğu + `done/`'a taşıma.

## Acceptance criteria

- Dört demo senaryosu TestClient üzerinden uçtan uca geçer; "altın an" senaryosunda cevapta REJECT gerekçesi (yüzde toplamı) görünür.
- Release çağrısı yalnızca `buyer_approved ∧ seller_approved ∧ decision ∈ {capture, partial_capture}` sağlanınca yapılır; dispute'ta hiçbir capture çağrısı yapılmaz (testle kanıtlı, §6.1).
- Validator kapısı atlanamaz: PASS almadan hiçbir extraction `awaiting_approval`'a geçmez; REJECT akışı durdurur (§6.2).
- Tüm modüller `eventbus.emit()` üzerinden iz bırakır; §4.3'teki dokuz event tipi doğru anlarda üretilir; evidence bundle bu zincirden derlenir ve ham PII/kart verisi içermez.
- Yanlış token her taraf endpoint'inde 403 döner; token'lar tahmin edilemez (`secrets`).
- Decision engine ve validator saf fonksiyondur — DB/network importu yoktur (test dosyalarında I/O'suz çağrılırlar).
- RAG bağımlılıkları kurulu değilken sistem bağlamsız graceful çalışır (mevcut davranış API'de de korunur); `LLM_PROVIDER=fake` default'uyla anahtar gerektirmez.
- Mevcut 91 test + yeni testler yeşil.

## Verification

```bash
cd code
./.venv/bin/python -m pytest -q                          # tüm suite
./.venv/bin/python -m pytest tests/test_validator.py tests/test_decision.py tests/test_api_flow.py -v
# Manuel duman testi:
./.venv/bin/uvicorn backend.app.main:app --reload        # /docs açılır
# curl sırası: POST /api/transactions (örnek PDF) → GET detay (extraction+validator raporu)
# → 2x POST approvals (buyer/seller token) → POST events/e-irsaliye → GET detay (decided/captured)
# → GET evidence (bundle'da event zinciri + maskeli içerik)
```

## Risks

- **En büyük plan bu — kapsam şişmesi.** Adım sınırları ve "router'lara §4.1 dışı endpoint eklenmez" kuralı disiplinle uygulanmalı; UI kolaylığı için endpoint icat edilmez (frontend planı ihtiyaç çıkarırsa mutabakatla eklenir).
- **SQLite + BackgroundTasks eşzamanlılığı:** tek uvicorn worker + WAL + per-request connection ile demo yükünde sorun beklenmez; test'lerde `TestClient` senkron çalışır. Çoklu worker **çalıştırılmaz** (dokümante edilir).
- **Pipeline süresi:** RAG deps kuruluysa ilk istekte BGE-M3 yüklenmesi dakikalar alabilir — upload cevabı hemen döndüğü için API bloklanmaz; demo öncesi ısıtma notu AGENTS pratik notlarına yazılır.
- **Decision eşikleri (%10 ayrışma, hasar sinyali) kabaca pinlendi** — demo fixture'ları bu eşiklerle uyumlu kurgulanmalı; gerekirse tek yerde sabit olarak tutulup ayarlanır.
- **NEEDS_REVIEW akışı UI'sız belirsiz kalabilir:** bu planda review çözümü = iki tarafın onayı (party-view uyarıları gösterir). Ayrı bir "review resolve" endpoint'i bilinçli olarak yok (§4.1'de tanımlı değil); frontend planında ihtiyaç doğarsa mutabakatla eklenir.
- **Mentor cevabı gelirse** (wallet contract'ı farklıysa) yalnızca `MockMokaProvider` iç şekli değişir — adapter sınırı sayesinde akış kodu etkilenmez (§3.3'ün tasarım gerekçesi).

## Notes for Implementer

- Uygulama `/plan-uygula plans/ready/backend_iskeleti_ve_islem_akisi.md` ile; doc-sync protokolü işin parçası.
- **Görevler kişiye etiketlenmez.**
- §6 değişmezleri bu planın her adımında geçerli — özellikle: release'i yalnızca deterministik akış çağırır (§6.1), validator kapısı atlanamaz (§6.2), her dış bağımlılık adapter+fake (§6.3), eventbus=events tablosu (§6.4), decision saf fonksiyon (§6.5), token=kimlik (§6.6), evidence'a maskeli içerik (§6.7/pci.req.10).
- Mevcut servislere (`extraction`, `privacy`, `context_builder`, `rag`) **dokunma** — pipeline onları çağırır. CLI (`extract_contract.py`) değişmez; ortak mantık kopyalanacaksa küçükçe paylaşılabilir ama CLI'ın davranışı bozulmaz.
- Ham `markdown` yalnızca `transactions` tablosunda; maskeleme haritası persist edilmez; API cevapları ve evidence maskeli içerikten üretilir.
- Kod yorumları/CLI-API mesajları Türkçe, tanımlayıcılar İngilizce; test ortamı `cd code && ./.venv/bin/python -m pytest`.
- `secrets.token_urlsafe(32)` token üretimi; token'lar loglanmaz.
- Testlerde gerçek PDF dönüşümünden kaçınmak için `md/txt` passthrough upload kullanılabilir (küçük fixture'lar); en az bir test gerçek küçük PDF fixture'ıyla tam yolu doğrular.
