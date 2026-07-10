# 04 — Document Provenance, Rule Versioning, Reconciliation, Ratification, Manual Review (Program 2)

> **Durum:** Ready — 2026-07-10 · **Master ref:** v2 §2.11, §2.15, §2.16, §5.8-5.15, Program 2, Wave 2-3 · Moka §9 (funding plan package'ta)
> **Bağımlılık:** 03 tamam. Integration branch: `program/domain-evolution-v2`
> **Branch'ler:** iki wave, aşağıda faz bazında
> **Tahmin:** 6-8 gün (paralel, iki wave)

## Amaç

"Kim, hangi kurum adına, tam olarak NEYİ onayladı?" sorusunu kanıtlanabilir yapmak: doküman/extraction provenance'ı, immutable rule-set versiyonları, extracted↔declared↔confirmed taraf mutabakatı, kilitli policy + **funding schedule** dahil kanonik ratification package'ı, package-hash'e bağlı çift ratification ve NEEDS_REVIEW'u çıkmaz sokak olmaktan çıkaran manuel inceleme. Bu planın sonunda **legacy token approval default kapanır** ve senaryo testleri account-fixture'a taşınır (v2 §2.2 Wave 3 cutover).

## Wave A — Versioning + Review

### Faz 4A — Document + extraction + rule-set versiyonları (Berke, `feat/document-rule-versioning`)

Dosya sınırı: `services/document_storage.py`, `repositories/rule_sets.py`, `db/migrations/008*`, `009*`, pipeline entegrasyonu (`transactions.py` + `services/transaction_pipeline.py`'ye taşıma).

1. **DocumentStorageProvider** port + `LocalDocumentStorageProvider` (`code/data/runtime/documents/`, gitignore) — v2 §2.11; upload bytes 03'te hesaplanan hash ile buraya yazılır, `storage_ref` döner.
2. **008_documents_extraction_runs:** `contract_documents` (v2 §5.8) + `extraction_runs` (v2 §5.9; provider/model/prompt_version/schema_version/RAG source IDs/privacy summary; raw çıktı immutable).
3. **009_rule_set_versions:** v2 §5.10; `rules_json` **ExtractionJSON-uyumlu payload'dır, şema değişmez**; `rules_hash` = sha256(kanonik JSON string).
4. Pipeline: upload → document row → extraction run → initial `rule_set_version` (validator her version için koşar; `validator_status` version'a yazılır). Bu vesileyle pipeline `routers/transactions.py`'den `services/transaction_pipeline.py`'ye taşınır (davranış aynı).
5. `repositories/rule_sets.py::get_current(transaction_id)` — beş kopya "latest-by-rowid" sorgusu (transactions/approvals/delivery/settlement/evidence) bu repository'ye taşınır. **Legacy uyum:** account işlemler `rule_set_versions`'tan, legacy işlemler `extracted_rules` fallback'inden okunur; legacy yazma yolu değişmez.

### Faz 4B — Review + party reconciliation (Yusuf, `feat/review-party-reconciliation`)

Dosya sınırı: `services/review.py`, `services/reconciliation.py`, `repositories/reviews.py`, `routers/reviews.py`, `db/migrations/010*`.

1. **010_review_cases:** `review_cases` + `review_actions` (v2 §5.14-5.15).
2. **ReviewService** — donmuş imzalar (v2 §8.3): `open_case / record_action / resolve_case / has_blocking_case`.
3. Pipeline entegrasyon kontratı: validator NEEDS_REVIEW → `source_type=validator` blocking case (account işlemlerde; legacy davranış değişmez). Party reconciliation: extracted vs declared vs confirmed diff → mismatch reason-code'ları → blocking case (`party_mismatch`). Sessiz overwrite yok (v2 4.6 ilkesi).
4. **Reviews API** (§14): GET list + POST actions (comment/request_evidence/resolve_continue/resolve_reject/escalate…); yetki: v2 §6.3 matrisi.

**Wave A gate:** NEEDS_REVIEW → case açılır → (4F'deki revision henüz yokken) resolve_reject/cancel çalışır; PASS akışı etkilenmez. Freeze: `RuleVersionService` + `ReviewService`.

## Wave B — Funding plan + package + ratification + recoverable review

### Faz 4C — Saf funding-plan compiler (Yusuf, `feat/funding-plan-compiler` — küçük, Wave B'nin İLK merge'i)

Dosya sınırı: `schemas/payments.py`, `services/payments/funding_plan.py` (saf; DB/HTTP yok).

1. Tipler (donmuş): `MilestoneDraft` (rule_index, title, trigger_type, basis_points, amount_minor, currency, required_evidence, release_mode) · `FundingUnitDraft` (sequence, amount_minor, eligibility_type/payload) · `FundingScheduleSpec` · `release_mode = all_or_nothing | fixed_tranches` (Moka §3.5; `proportional_to_verified_quantity` Moka profilinde **reddedilir** → `PROVIDER_CAPABILITY_CONFLICT / MOKA_REQUIRES_FIXED_FUNDING_UNITS`).
2. `compile_funding_plan(rule_set, total_amount_minor, currency, spec, capabilities)`: yüzde → basis points → minor units, **deterministic largest-remainder** (v2 §2.3); milestone → 1 unit (all_or_nothing) veya N sabit tranche (toplam tam eşit); deterministik default spec türetici (her milestone tek unit; e-irsaliye'li teslimat milestone'ları için spec ile tranche tanımlanabilir — LLM release mode BELİRLEYEMEZ).
3. Tutar kaynağı: `commercial_terms.total_amount` (float) → minor'a çevrim **tek yerde** (`to_minor()`, yarım-kuruş politikası testli). Table-driven testler: 20/30/40/10 → 4 milestone, toplam exact; 100 koli → 4×25 tranche şablonu.

### Faz 4D — Canonical package + FundingCoordinator v1 (Berke, `feat/ratification-package-canonicalization`)

Dosya sınırı: `services/ratification_package.py`, `services/payments/funding_coordinator.py`, `repositories/packages.py`, `db/migrations/011*`.

1. **011_ratification_packages:** v2 §5.12 + `funding_schedule` kanonik payload'ın içinde (Moka §9.5: provider_profile, unit sequence/amounts/eligibility, OtherTrxCode türetme versiyonu).
2. Kanonik serializer (v2 §2.15): sort_keys + sabit separators + UTF-8; **tutarlar minor int** (float yok); string bir kez üretilip saklanır; `package_hash = sha256(stored bytes)`; golden testler (aynı payload aynı hash, alan sırası bağımsız, tek alan değişimi farklı hash).
3. Package girdileri: document hash · rule_set id/version/hash · buyer+seller confirmed snapshot · **tracking policy snapshot** (mevcut `tracking_policies` satırından; versioned tablo 09'a ertelendi — harita §4 kararı) · funding schedule (4C compiler çıktısı) · commercial özet · schema_version. `supersede_if_inputs_changed` — policy/rule/participant değişimi package'ı superseded yapar (v2 §4.5 → burada 2E+2F birleşik).
4. **FundingCoordinator v1** (donmuş imza, v2 §8.5): bu fazda provider tarafı **mevcut tek-pool MockMokaProvider** ile çalışır (funding unit persistence 06'da): package complete + çift ratification + blocking review yok → `create_pool_payment(total)` exactly-once → `funding_pending→active`. 06'da altı funding-unit'lere değişecek, imza değişmeyecek.

### Faz 4E — Account ratification API + legacy cutover (Yusuf, `feat/account-ratification-api`)

Dosya sınırı: `routers/ratifications.py`, `repositories/ratifications.py`, `db/migrations/012*`, `routers/approvals.py` (cutover), test fixture göçü.

1. **012_ratifications:** v2 §5.13, `UNIQUE(package_id, participant_id)`.
2. **API** (§14): `POST ratification-packages` (build/open; yalnız ready_for_ratification — v2 §7.3) · `GET current` (iki tarafa aynı projection + aynı hash) · `POST ratifications` (participant approver; idempotent; superseded package → 409; aynı user iki taraf adına → 403). Ratification tamamlanınca `FundingCoordinator.ensure_funded` çağrılır — **router provider'ı doğrudan çağırmaz** (Moka §18.2).
3. **Legacy cutover (v2 §2.2 Wave 3):** `LEGACY_CAPABILITY_ACCESS_ENABLED` default **false**'a çekilir (env ile açılabilir); senaryo regression testleri (approval-only, document-only, optional video, video anomaly, partial delivery) account-based fixture'lara taşınır; legacy fixture'lar `legacy_compat` işaretli dar bir sette yaşamaya devam eder.

### Faz 4F — Recoverable manual review (Yusuf, `feat/recoverable-review`)

1. `POST rule-sets/{version}/revisions` → **yeni immutable version** (eski satır overwrite edilmez) + otomatik re-validate (`POST .../validate` da açık uç olarak) — yalnız creator-side manager, pre-ratification (v2 §6.3).
2. Review resolve akışı: validator/mismatch case'i çözülünce account işlem `preparation`'a döner; PASS olmayan version ratifiable olamaz; blocking case package açılmasını engeller. **awaiting_review artık account akışında çıkmaz sokak değildir** (legacy davranış değişmez).

## Paralellik ve merge sırası

Wave A: 4A ∥ 4B → gate. Wave B: önce 4C (küçük, freeze), sonra 4D ∥ 4E, en son 4F. `approvals.py` yalnız Yusuf'ta (cutover); `transactions.py`/pipeline yalnız Berke'de; funding provider çağrısı yalnız FundingCoordinator'da.

## Kabul kriterleri

v2 Program 2 listesi birebir (raw extraction immutable · revision yeni version · same payload same hash · stored-bytes hash · NEEDS_REVIEW recoverable · superseded package funding yapamaz · iki taraf aynı hash'i görür · funding exactly once · legacy approval default off · fixture cutover) + 4C compiler tabloları + `PROVIDER_CAPABILITY_CONFLICT` reddi.

## Repo güvenliği

Tüm migration'lar additive; legacy path env ile geri açılabilir; `extracted_rules`/`approvals` tabloları silinmez (removal gate v2 §15.4). Cutover tek fazda (4E) ve gate senaryosu yeşilken yapılır.

## Doc-sync

ARCHITECTURE §1 (yeni servisler), §3.3 (FundingCoordinator), §4.1 (rule-sets/reviews/ratification uçları; approvals'ın legacy'e düşmesi), §4.2'ye NOT (şema değişmedi; rule_set_versions aynı şemayı taşır), §5 (yeni tablolar + package/ratification state'leri), §6 (6.11 amendment kuralının "yeni package" modeliyle güncellenmesi); AGENTS özet.
