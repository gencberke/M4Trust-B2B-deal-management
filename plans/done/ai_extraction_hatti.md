> **Cost-oriented workflow — anchor. Re-read this block each loop.**
> MODE: standard
> COMMIT_POLICY: user-owned  (controller does NOT commit/push; work lands on a feature branch, Berke commits)
> BRANCH: `feature/ai-extraction-hatti` — create before the first tracked edit (non-trivial work, do not build on master)
> ROUTING: brainstorm-gate (done) → this plan/contract → delegate-by-contract-cost (inline when the contract would cost more than the code) → review-per-risk-matrix → verify-before-done
> CADENCE: continuous — run planned tasks without pausing; STOP only on: blocked · decision ambiguity · plan/code conflict · scope or risk escalation · external/irreversible action · retry budget exhausted · new credential or permission · failed baseline/verification · human asked to checkpoint
> ON RESUME/COMPACTION: if `COW_ENTRY_INJECTED` is absent, invoke cost-oriented-agentic-workflow:using-cost-oriented-workflow exactly once; if present, do not reload it. In both cases trust this plan + the per-worktree progress ledger + git log over memory.

> **Durum:** Uygulandı — 2026-07-08 · Sapmalar: (1) `privacy.py` §6.7 için öne çekildi (yol haritasında day-3'teydi). (2) Env bootstrap: `code/.venv` (py3.12); ağır RAG deps (chromadb/FlagEmbedding/torch) ertelendi ve `rag.py`'de lazy — canlı RAG için `pip install -r requirements.txt` gerekir, yoksa CLI bağlamsız devam eder. (3) Task 2 bağımsız review'ı bütün-iş review'ına devredildi (şema mekanik + downstream-exercised). (4) Task 4: grouped/spaced IBAN leak (Critical) bulundu+düzeltildi (1 remediation wave). (5) Task 5: None/empty içerik için retry-guard eklendi. (6) Task 6: restore sonrası doğrulama guard'ı eklendi (bütün-iş review bulgusu F-001). Tüm testler: 58 geçiyor. Commit user-owned (branch `feature/ai-extraction-hatti`, commit'lenmedi).

# AI Extraction Hattı Plan

**Goal:** Sözleşme PDF'inden ARCHITECTURE §4.2 şemasına uygun yapılandırılmış kural JSON'u üreten uçtan uca AI extraction hattını kur (RAG retrieval + canlı OpenAI-uyumlu structured output), maskeleme ile §6.7'yi ihlal etmeden.

**Approach:** ARCHITECTURE §1/§3.1/§3.2/§3.5/§4.2'yi birebir uygula: `backend/app/` altında donmuş Pydantic extraction şeması, BGE-M3+Chroma RAG retriever, minimal PII maskeleme (mask+local restore-map), ve `ExtractionService` (Fake + canlı OpenAI-uyumlu adapter, env ile seçilir). `scripts/extract_contract.py` bu parçaları CLI olarak birleştirir: convert → mask → retrieve → extract → restore → validate. Mevcut kod stili (DI + ABC port + pytest Fake) korunur.

## Global Constraints

- **Dil:** tüm kod yorumları/CLI çıktısı/doküman Türkçe; kod tanımlayıcıları İngilizce (mevcut `document_parser` stili).
- **§6.7 (değişmez):** dış LLM çağrısına yalnızca **maskelenmiş** içerik gider. Canlı çağrıdan önce `privacy.mask()` uygulanmadan `extract()` çağrılamaz. Bu, hattın kabul kriteridir, opsiyon değil.
- **§4.2 ikili sözleşme:** `schemas/extraction.py` şeması ARCHITECTURE §4.2 ile alan-alan aynıdır; **alan ekleme/çıkarma/yeniden adlandırma yapılmaz** (değişiklik ekip mutabakatı ister — bu plan mutabakat içermez).
- **§3 adapter+fake:** her dış bağımlılık (LLM) bir interface arkasında + Fake çiftiyle; seçim env ile (`LLM_PROVIDER`). Default `fake` (demo-güvenli).
- **§3.2 RAG:** korpus BGE-M3 ile embed'li; sorgu da BGE-M3 `encode(...)["dense_vecs"]` ile encode edilir. Model lazy singleton, CPU, `use_fp16=False`. Koleksiyonlar: `legal_articles`, `contract_examples`. Chroma yolu `code/data/processed/embeddings/chroma/`.
- **Import kökü:** backend paketi `code/` kökünden (`from backend.app...`); parser `code/scripts/` kökünden (`from document_parser...`). Testler `code/` CWD'den çalışır; `pytest` komutları `cd code` varsayar.
- **Secrets:** `LLM_API_KEY` yalnızca env/`.env`'den okunur; **asla loglanmaz, asla commit'lenmez**; `.env` gitignore'da.
- **Python:** 3.12. Pydantic v2 (chromadb 1.5.9 üzerinden mevcut; Task 2'de explicit pinlenir ve v2 doğrulanır).
- **Bağımsız modelin ödeme yetkisi yoktur:** bu hat yalnızca kural **önerir**; hiçbir ödeme/validator/DB yazımı bu kapsamda değildir. Çıktı "önerilen kural"dır.

---

## Decomposition (dosya sahipliği + tek sorumluluk)

| Task | Sorumluluk | Create/Modify | Risk |
|---|---|---|---|
| 1 | Backend paket iskeleti + env config + import wiring | `backend/__init__.py`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/.env.example`; mod `tests/conftest.py`, `.gitignore` | low |
| 2 | Donmuş extraction şeması (§4.2) | `backend/app/schemas/__init__.py`, `backend/app/schemas/extraction.py`; mod `requirements.txt` (pydantic) | elevated |
| 3 | RAG retriever (BGE-M3 + Chroma) | `backend/app/services/__init__.py`, `backend/app/services/rag.py` | low |
| 4 | Privacy mask + restore (§3.5/§6.7 sınırı) | `backend/app/services/privacy.py` | elevated |
| 5 | ExtractionService (Fake + canlı OpenAI-uyumlu) | `backend/app/services/extraction.py`; mod `requirements.txt` (openai) | elevated |
| 6 | CLI pipeline wiring | `scripts/extract_contract.py` (mod, şu an boş) | low |
| 7 | doc-sync (ARCHITECTURE/AGENTS/plan durum) | mod `ARCHITECTURE.md`, `AGENTS.md`, bu plan | low |

Sıra bağımlılığı: 1 → 2 → (3, 4 paralel-safe ama sıralı yürütülür) → 5 → 6 → 7. Task 5, Task 2+4'ün ürettiği tipleri tüketir; Task 6, hepsini tüketir.

---

### Task 1: Backend paket iskeleti + config + import wiring

**Files:**
- Create: `code/backend/__init__.py` (boş), `code/backend/app/__init__.py` (boş), `code/backend/app/config.py`, `code/backend/.env.example`
- Modify: `code/tests/conftest.py` (ek sys.path), `.gitignore` (`.env` ve `code/.env` ignore; Chroma index'in ignore EDİLMEDİĞİNİ doğrula)

**Interfaces (pin the seams):**
- Produces: `backend.app.config.Settings` (frozen dataclass) alanları:
  - `llm_provider: str` (env `LLM_PROVIDER`, default `"fake"`)
  - `llm_base_url: str` (env `LLM_BASE_URL`, default `"https://api.openai.com/v1"`)
  - `llm_model: str` (env `LLM_MODEL`, default `"gpt-5.4-mini"`)  ← ekip kararı (ARCHITECTURE'daki "5.4 mini"); env ile override edilebilir
  - `llm_api_key: str` (env `LLM_API_KEY`, default `""`)
  - `llm_timeout: float` (env `LLM_TIMEOUT`, default `60`)
  - `chroma_dir: Path` (default `code/data/processed/embeddings/chroma`, `config.py` konumundan `.resolve()` ile türetilir — CWD'ye bağımlı olmasın)
  - `rag_model_name: str` (default `"BAAI/bge-m3"`), `legal_collection: str` (`"legal_articles"`), `contract_collection: str` (`"contract_examples"`)
  - classmethod `Settings.from_env() -> Settings`
- Produces: `code/` kökü tüm testlerin sys.path'inde (mevcut `scripts` ek satırı korunur).

**Route hint:** inline — küçük, tek dosya-grubu iskele; contract koddan pahalı.
**Acceptance:** `Settings.from_env()` env yokken default'ları döndürür; `LLM_PROVIDER=openai` env'i set edilince `.llm_provider=="openai"`. `.env.example` tüm env değişkenlerini örnek değerlerle içerir, gerçek secret İÇERMEZ. conftest hem `document_parser` (bare) hem `backend.app...` importlarını mümkün kılar. `config.py` hiçbir yerde `llm_api_key` yazdırmaz/loglamaz.
**Verify:** `cd code && python -c "import sys; sys.path.insert(0,'.'); from backend.app.config import Settings; s=Settings.from_env(); print(s.llm_provider, s.chroma_dir.exists())"` → `fake True`

---

### Task 2: Donmuş extraction şeması (§4.2)

**Files:**
- Create: `code/backend/app/schemas/__init__.py`, `code/backend/app/schemas/extraction.py`
- Modify: `code/requirements.txt` (explicit `pydantic>=2,<3` ekle — chromadb üzerinden zaten mevcut, sadece açık pinle)

**Interfaces (pin the seams):**
- Produces (ARCHITECTURE §4.2 ile alan-alan aynı, Pydantic v2):
  - `Currency(str, Enum)`: `TRY, USD, EUR, OTHER`
  - `Trigger(str, Enum)`: `approval, e_invoice, delivery_video, manual_review`
  - `RequiredEvidence(str, Enum)`: `contract, e_irsaliye, video`
  - `Party`: `name: str`, `tax_id: str | None = None`
  - `Parties`: `buyer: Party`, `seller: Party`
  - `Goods`: `name: str`, `quantity: float`, `unit: str`
  - `CommercialTerms`: `currency: Currency`, `total_amount: float`, `goods: list[Goods]`, `delivery_deadline: str | None` (YYYY-MM-DD veya null; validator ile doğrula)
  - `PaymentRule`: `milestone: str`, `trigger: Trigger`, `percentage: float` (0–100), `required_evidence: list[RequiredEvidence]`, `source_quote: str`, `confidence: float` (0.0–1.0)
  - `ExtractionJSON`: `contract_id: str`, `parties: Parties`, `commercial_terms: CommercialTerms`, `payment_rules: list[PaymentRule]`, `risk_flags: list[str]`, `needs_manual_review: bool = False`
  - Tüm modeller `model_config = ConfigDict(extra="forbid")` (şema ikili sözleşme — fazladan alan reddedilir).

**Risk:** elevated — §4.2 ikili sözleşme; RAG/extraction/validator/frontend hepsi buna bağlanır. Yanlış alan = tüm hatta yayılan hata.
**Route hint:** delegate — çok alanlı, validator'lı; self-contained ve iyi test edilir.
**Acceptance (behavioral):**
- Geçerli tam payload (§4.2 örneği) `ExtractionJSON.model_validate(...)` ile parse olur.
- `percentage=150` → `ValidationError`; `confidence=1.5` → `ValidationError`; `currency="GBP"` → `ValidationError`; `trigger="foo"` → `ValidationError`; `delivery_deadline="2026/01/01"` → `ValidationError` (format), `null` → geçerli.
- Bilinmeyen alan (`{"foo": 1, ...}`) → `ValidationError` (extra forbid).
- Şema §4.2 ile alan-alan eşleşir (fazladan/eksik alan yok).
**Verify:** `cd code && python -m pytest tests/test_extraction_schema.py -q` → tüm testler geçer; ayrıca `python -c "import pydantic,sys; assert pydantic.VERSION.startswith('2'), pydantic.VERSION; print('pydantic', pydantic.VERSION)"` → v2.

---

### Task 3: RAG retriever (BGE-M3 + Chroma)

**Files:**
- Create: `code/backend/app/services/__init__.py`, `code/backend/app/services/rag.py`

**Interfaces (pin the seams):**
- Consumes: `backend.app.config.Settings` (chroma_dir, rag_model_name, koleksiyon adları).
- Produces:
  - `@dataclass(frozen=True) Chunk`: `text: str`, `source: str`, `strategy: str`, `madde_no: str | None`, `heading: str | None`, `score: float`
  - `Retriever` sınıfı:
    - `__init__(self, settings: Settings, *, client=None, model=None)` — client/model enjekte edilebilir (test için); verilmezse lazy oluşturulur.
    - lazy `_get_model()` → `BGEM3FlagModel(settings.rag_model_name, use_fp16=False)` (singleton, ilk çağrıda yüklenir)
    - lazy `_get_client()` → `chromadb.PersistentClient(path=str(settings.chroma_dir))`
    - `retrieve(self, query: str, collection: str | None = None, k: int = 5) -> list[Chunk]` — `collection` None ise `settings.legal_collection`. Sorguyu `model.encode([query])["dense_vecs"]` ile encode eder, `collection.query(query_embeddings=..., n_results=k)` çağırır, sonucu `Chunk`'a map'ler (documents→text, metadatas→source/strategy/madde_no/heading, distances→score).
  - `FakeRetriever`: `retrieve(...)` sabit bir `list[Chunk]` döndürür (downstream/test için).

**Route hint:** delegate — Chroma/BGE-M3 mapping + lazy singleton; interior emek koddan çok.
**Acceptance:** Enjekte edilmiş fake client+model ile `retrieve("teslimat", "legal_articles", k=3)`:
- query, `model.encode` çağrısından geçer (BGE-M3 kuralı); `collection.query` `n_results=3` ile çağrılır;
- dönen Chroma yapısı (`documents`, `metadatas`, `distances` listeleri) doğru şekilde `Chunk` listesine map'lenir; eksik `madde_no`/`heading` → `None`.
- `collection=None` → `legal_articles` kullanılır.
Canlı model yüklemesi unit testte GEREKMEZ (enjekte edilen fake ile). Canlı doğrulama opsiyonel (Task 6 verify'ında).
**Verify:** `cd code && python -m pytest tests/test_rag.py -q` → geçer.

---

### Task 4: Privacy mask + restore (§3.5 / §6.7 sınırı)

**Files:**
- Create: `code/backend/app/services/privacy.py`

**Interfaces (pin the seams):**
- Produces:
  - `@dataclass MaskResult`: `masked_text: str`, `mapping: dict[str, str]` (placeholder → orijinal)
  - `mask(text: str) -> MaskResult` — şu PII'leri deterministik placeholder token'larla değiştirir: TCKN (11 haneli, kelime sınırı), VKN/vergi no (10 haneli), IBAN (`TR` + 24 karakter), telefon (TR formatları: `+90`, `0(5xx)`, boşluk/tire varyasyonları), e-posta. Token formatı `[[PII_<TIP>_<n>]]` (ör. `[[PII_IBAN_1]]`). Aynı orijinal değer → aynı token (idempotent).
  - `restore(obj, mapping)` — `str | dict | list` üzerinde recursive; her string değerdeki placeholder'ı `mapping`'ten orijinaliyle değiştirir; `ExtractionJSON`'ın `model_dump()` çıktısı gibi iç içe yapıda çalışır.

**Risk:** elevated — bu, §6.7 dış-çağrı güvenlik sınırıdır. Mask kaçağı = canlı LLM'e PII sızması. Yüksek özenle + davranışsal test.
**Route hint:** delegate — regex tasarımı + recursive restore; kaçak riski nedeniyle bağımsız gözden geçirme gerektirir.
**Acceptance (behavioral):**
- TCKN `12345678950`, VKN `1234567890`, IBAN `TR330006100519786457841326`, telefon `+90 532 111 22 33`, e-posta `a@b.com` içeren markdown → `masked_text` bu orijinallerin HİÇBİRİNİ içermez; her biri bir `[[PII_..._n]]` token'ıyla değişmiştir.
- `restore(mask(t).masked_text, mask(t).mapping) == t` (round-trip).
- `restore({"tax_id":"[[PII_VKN_1]]","nested":["[[PII_IBAN_1]]"]}, mapping)` → placeholder'lar orijinallere döner.
- Aynı değer iki kez geçerse aynı token (idempotent); PII olmayan sayı (ör. miktar `100`) maskelenmez (11/10 hane kuralı + bağlam).
**Verify:** `cd code && python -m pytest tests/test_privacy.py -q` → geçer.

---

### Task 5: ExtractionService (Fake + canlı OpenAI-uyumlu)

**Files:**
- Create: `code/backend/app/services/extraction.py`
- Modify: `code/requirements.txt` (`openai>=1.40` ekle — kullanıcı onayladı; canlı sağlayıcı)

**Interfaces (pin the seams):**
- Consumes: `ExtractionJSON` (Task 2), `Chunk` (Task 3), `Settings` (Task 1).
- Produces:
  - `@dataclass ExtractionResult`: `status: Literal["ok","needs_review"]`, `data: ExtractionJSON | None`, `reason: str | None` (needs_review nedeni).
  - `class ExtractionService(ABC)`: `extract(self, masked_markdown: str, rag_context: list[Chunk]) -> ExtractionResult`
  - `FakeExtractionService(ExtractionService)`: §4.2 örneğiyle uyumlu, şema-geçerli bir `ExtractionJSON` fixture'ı döndürür (`status="ok"`). Fixture demo-güvenli (her zaman çalışır).
  - `OpenAICompatibleExtractionService(ExtractionService)`:
    - `__init__(self, settings, *, client=None)` — `client` verilmezse lazy `import openai; openai.OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=settings.llm_timeout)`.
    - `extract`: sistem promptu + `masked_markdown` + `rag_context` (chunk metinleri) ile structured-output çağrısı; çıktı `ExtractionJSON`'a doğrulanır. Şema-geçersiz cevap → **1 kez retry**; yine geçersiz → `ExtractionResult(status="needs_review", reason=...)` (§3.1). Ağ/SDK hatası → `needs_review` (fixture'a düşmez; hata yutulmaz, reason'a yazılır).
    - Girdi olarak yalnızca `masked_markdown` gönderir (maskeleme upstream'de yapılmıştır — §6.7 sırası CLI'da garanti edilir).
  - `make_extraction_service(settings: Settings) -> ExtractionService` — `settings.llm_provider` `"openai"` ise canlı, aksi halde `Fake` (default).

**Risk:** elevated — dış API çağrısı + onaylı yeni bağımlılık (`openai`) + hattın çekirdeği.
**Route hint:** delegate — SDK entegrasyonu + retry/needs_review mantığı + factory; çok parçalı.
**Acceptance (behavioral):**
- `FakeExtractionService().extract("...", [])` → `status="ok"`, `data` şema-geçerli `ExtractionJSON`.
- `OpenAICompatibleExtractionService` MOCK'lanmış client ile (unit testte gerçek ağ YOK):
  - mock geçerli JSON döndürür → `status="ok"`, doğru `ExtractionJSON`;
  - mock önce geçersiz sonra geçerli döndürür → retry edilir, `status="ok"`;
  - mock iki kez geçersiz döndürür → `status="needs_review"`, `reason` dolu;
  - mock exception fırlatır → `status="needs_review"`, `reason` hata mesajını içerir.
- `make_extraction_service(Settings(llm_provider="fake"))` → `FakeExtractionService`; `"openai"` → `OpenAICompatibleExtractionService`.
**Verify:** `cd code && python -m pytest tests/test_extraction.py -q` → geçer.

---

### Task 6: CLI pipeline wiring (`extract_contract.py`)

**Files:**
- Modify: `code/scripts/extract_contract.py` (şu an boş)

**Interfaces (pin the seams):**
- Consumes: `DocumentConverter` (`document_parser`), `privacy.mask/restore`, `Retriever`/`make` (rag), `make_extraction_service` (extraction), `ExtractionJSON`, `Settings`.
- Produces:
  - Testlenebilir çekirdek: `run_extraction(pdf_path: Path, *, settings: Settings, converter=None, retriever=None, extraction_service=None) -> ExtractionResult` — deps verilmezse gerçekleri kurulur (DI, `document_parser` stiliyle). Sıra: `convert(pdf)` → `mask(markdown)` → `retrieve(sorgu, legal_collection)` (sorgu maskeli metinden türetilir) → `extract(masked, chunks)` → sonuç `ok` ise `restore(data.model_dump(), mapping)` → `ExtractionJSON.model_validate(...)` (restore sonrası tekrar doğrula).
  - `main()`: argparse `pdf_path`, `--provider {fake,openai}` (default env/`settings`), `--collection`, `--k`, `--out PATH`. sys.path köprüsü (hem `code/` hem `code/scripts`). Çıktı: `status=ok` → JSON stdout/`--out`; `needs_review` → reason'ı stderr'e yazar, exit 2.

**Route hint:** delegate — çok parçalı entegrasyon + argparse + DI çekirdeği.
**Acceptance (behavioral):**
- Fake deps enjekte edilerek `run_extraction(...)` uçtan uca çalışır ve şema-geçerli `ExtractionResult(status="ok")` döndürür; pipeline sırası: convert→mask→retrieve→extract→restore→validate (masked metnin extract'e gittiği, restore sonrası orijinal PII'nin geri geldiği test edilir → §6.7 seam garantisi).
- **§6.7 davranışsal:** mock extraction_service'e giden `masked_markdown` argümanı ham PII içermez (mask önce çalışmış).
- CLI smoke: `--provider fake` ile gerçek/fixture bir PDF üzerinden `main()` şema-geçerli JSON basar, exit 0.
**Verify:** `cd code && python -m pytest tests/test_extract_contract_cli.py -q` → geçer. Canlı opsiyonel (kullanıcı çalıştırır): `.env`'e gerçek `LLM_*` doldurulup `cd code && python scripts/extract_contract.py <ornek.pdf> --provider openai` → şema-geçerli JSON.

---

### Task 7: doc-sync (ARCHITECTURE / AGENTS / plan durum)

**Files:**
- Modify: `ARCHITECTURE.md`, `AGENTS.md`, `plans/v2/v2_ai_extraction_hatti.md` (bu dosya — durum bloğu)

**Interfaces (pin the seams):** yok (dokümantasyon).
**Acceptance:**
- ARCHITECTURE §1 dizin ağacı: `services/rag.py`, `services/privacy.py`, `services/extraction.py`, `schemas/extraction.py` artık "var" — gerekiyorsa notla; §2 stack'e `openai` (LLM SDK) eklendiğini yansıt; §3.5 privacy'nin minimal (regex PII, mask+restore-map) uygulandığını, tam maskelemenin (adres/isim nüansları) sonraya kaldığını not et.
- AGENTS.md "Pratik notlar": `extract_contract.py` artık dolu (CLI hattı); minimal `privacy.py` §6.7 için öne çekildi; `openai` bağımlılığı eklendi.
- Bu planın durum bloğu: `> **Durum:** Uygulandı — 2026-07-08 · Sapmalar: …`
- Sapma yoksa doc-sync raporunda "değişiklik gerekmedi" denmez — bu iş dokümanları eskitiyor, güncelleme zorunlu.
**Verify:** `git diff --stat ARCHITECTURE.md AGENTS.md` → her ikisi de değişmiş; plan durum bloğu "Uygulandı" gösterir.

---

## Self-review (controller — tamamlandı)

1. **Coverage:** §4.2 şema→T2; §3.2 RAG→T3; §3.5/§6.7 mask→T4; §3.1 ExtractionService+adapter+fake→T5; §1 CLI/pipeline→T6; config/env/deps→T1(+T2 pydantic, T5 openai); doc-sync→T7. Kullanıcı seçimleri (AI hattı + canlı OpenAI çağrı) T5'te; şema-önce-donar önkoşulu T2'de. Boşluk yok.
2. **Placeholder scan:** TBD/TODO yok; her task'ın somut kabul + verify komutu var.
3. **Interface consistency:** `Chunk` (T3) → T5.extract `rag_context: list[Chunk]` → T6 pipeline; `ExtractionJSON` (T2) → T5/T6; `Settings` (T1) → T3/T5/T6; `make_extraction_service` (T5) → T6; `mask/restore` (T4) → T6. İsimler eşleşiyor.
4. **Internal consistency:** §6.7 kısıtı (mask-önce) T4+T6 kabulleriyle tutarlı; §4.2 "alan değişmez" T2 ile tutarlı; adapter+fake default=fake T1(config)+T5(factory) ile tutarlı. Çelişki yok.
