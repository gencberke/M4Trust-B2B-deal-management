# 04 — Document Provenance, Rule Versioning, Reconciliation, Ratification, Manual Review (Program 2)

> **Durum:** Uygulandı — 2026-07-11 · Sapmalar: Account legacy capability default-false cutover ve gerçek provider funding, ekip kararına uygun olarak Plan 06'ya bırakıldı. **Master ref:** v2 §2.11, §2.15, §2.16, §5.8-5.15, Program 2, Wave 2-3 · Moka §9 (funding plan package'ta)
> **Wave A durumu:** Uygulandı — 2026-07-11 · 4A/4B + kapanış entegrasyonu tamamlandı; migration 010 registry, reviews app wiring, validator/reconciliation hook'ları ve merkezi reader seam gate'i yeşil. (Bu satır Wave A kapanışında yazıldı; Wave B'nin durumu aşağıdaki Faz 4C-4F-2 satırlarında ve **Plan 04 kapanış durumu** satırında ayrıca izlenir — bu satırın kendisi Wave B'nin bitip bitmediğini göstermez.)
> **Faz 4C durumu:** Uygulandı — 2026-07-11 · Yusuf’un saf funding-plan compiler’ı integration branch’e merge edildi.
> **Faz 4D durumu:** Uygulandı — 2026-07-11 · Canonical ratification package, migration 011, account lifecycle helper ve provider’sız FundingCoordinator v1 tamamlandı.
> **Faz 4E durumu:** Uygulandı — 2026-07-11 · Yusuf’un account ratification API, migration 012 dosyası ve approvals legacy cutover PR’ı integration branch’e merge edildi; kapanışta 012 registry/app wiring tamamlandı.
> **Faz 4F-1 durumu:** Uygulandı — 2026-07-11 · Creator-side manager rule revision/revalidation API’si, stale-parent CAS, otomatik validation/review hook’u, package supersede ve app wiring tamamlandı.
> **Faz 4F-2 durumu:** Uygulandı — 2026-07-11 · Yusuf tarafından tamamlandı ve integration branch’e merge edildi; blocking review resolution, account state recovery ve package gate akışı kapandı.
> **Plan 04 kapanış durumu:** Uygulandı — 2026-07-11 · `integration/plan-04-close` üzerinde migration/app wiring, gerçek app E2E gate’i, doc-sync ve kabul kontrolleri tamamlandı. Kapanış full suite: **765 passed, 30 warnings**.
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
4. **FundingCoordinator v1** (donmuş imza, v2 §8.5): **bu fazda provider ÇAĞRISI YAPMAZ.** `ready_for_funding` (package complete + çift ratification + blocking review yok) sağlanınca işlemi `funding_pending` durumuna alır ve `funding_required` event/audit kaydı düşer; gerçek funding (funding-unit modeliyle, exactly-once) **06'dadır**. Gerekçe (harita Revizyon #1): taraflar tranche'lı funding schedule'ı onaylarken tek-pool toplam ödeme açmak, ratify edilen package ile fiili funding davranışını koparır ve 06'da atılacak kod üretirdi. İmza 06'da değişmez, yalnız implementasyon dolar.

### Faz 4E — Account ratification API + legacy cutover (Yusuf, `feat/account-ratification-api`)

Dosya sınırı: `routers/ratifications.py`, `repositories/ratifications.py`, `db/migrations/012*`, `routers/approvals.py` (cutover), test fixture göçü.

1. **012_ratifications:** v2 §5.13, `UNIQUE(package_id, participant_id)`.
2. **API** (§14): `POST ratification-packages` (build/open; yalnız ready_for_ratification — v2 §7.3) · `GET current` (iki tarafa aynı projection + aynı hash) · `POST ratifications` (participant approver; idempotent; superseded package → 409; aynı user iki taraf adına → 403). Ratification tamamlanınca `FundingCoordinator.ensure_funded` çağrılır — **router provider'ı doğrudan çağırmaz** (Moka §18.2).
3. **Kısmi cutover (v2 §2.2'den bilinçli sapma — harita Revizyon #2):** Bu fazda yalnız **identity / rule-version / review / package / ratification** testleri account-mode'a taşınır. Ödeme ve kanıt senaryoları (approval-only tam ödeme, document-only, partial delivery, video) **legacy fixture'da kalır** ve `LEGACY_CAPABILITY_ACCESS_ENABLED` default **true** kalır — account evidence uçları 05'te, funding/settlement 06'da geldiği için bu senaryolar 04'te account-mode'da uçtan uca koşamaz. Tam fixture göçü + default-false cutover'ı **06'nın kapanışıdır**.

### Faz 4F — Recoverable manual review (iki küçük paralel parça — harita Revizyon #5)

**4F-1 (Berke, `feat/rule-revision-endpoints`):** `POST rule-sets/{version}/revisions` → **yeni immutable version** (eski satır overwrite edilmez) + otomatik re-validate (`POST .../validate` da açık uç olarak) — yalnız creator-side manager, pre-ratification (v2 §6.3). Gerekçe: bu uçlar Berke'nin 4A domain dosyalarına (`repositories/rule_sets.py`, rule-set router'ı) yazar; Yusuf'a verilmesi aynı dosyalara ikinci yazar sokardı.

**4F-2 (Yusuf, `feat/review-resolution-flow`):** Review resolve akışı: validator/mismatch case'i çözülünce account işlem `preparation`'a döner (geçiş `transaction_state` üzerinden); PASS olmayan version ratifiable olamaz; blocking case package açılmasını engeller. **awaiting_review artık account akışında çıkmaz sokak değildir** (legacy davranış değişmez).

## Paralellik ve merge sırası

Wave A: 4A ∥ 4B → gate. Wave B: önce 4C (küçük, freeze), sonra 4D ∥ 4E, en son 4F-1 ∥ 4F-2. Yük dengesi: Berke = 4A+4D+4F-1 · Yusuf = 4B+4C+4E+4F-2. 4E'deki fixture göçünde herkes **kendi** domain testlerini taşır (Berke: identity/entity/rule-version · Yusuf: participant/review/ratification). `approvals.py` yalnız Yusuf'ta (cutover); `transactions.py`/pipeline ve rule-set dosyaları yalnız Berke'de; funding provider çağrısı yalnız FundingCoordinator'da. Not: 4A'nın diğer router'lardaki mekanik "latest-by-rowid → repository" değişiklikleri Wave A'da biter; Yusuf 4E'ye Wave B'de güncel HEAD ile başlar.

## Kabul kriterleri

v2 Program 2 listesinin bu faza düşenleri (raw extraction immutable · revision yeni version · same payload same hash · stored-bytes hash · NEEDS_REVIEW recoverable · superseded package `funding_pending` üretemez · iki taraf aynı hash'i görür) + çift ratification → `funding_pending` + `funding_required` kaydı (provider çağrısı YOK) + 4C compiler tabloları + `PROVIDER_CAPABILITY_CONFLICT` reddi. **"Funding exactly once" ve "legacy default off + tam fixture cutover" kabulleri 06'ya taşındı** (harita Revizyon #1-2).

## Repo güvenliği

Tüm migration'lar additive; legacy path env ile geri açılabilir; `extracted_rules`/`approvals` tabloları silinmez (removal gate v2 §15.4). Cutover tek fazda (4E) ve gate senaryosu yeşilken yapılır.

## Doc-sync

ARCHITECTURE §1 (yeni servisler), §3.3 (FundingCoordinator), §4.1 (rule-sets/reviews/ratification uçları; approvals'ın legacy'e düşmesi), §4.2'ye NOT (şema değişmedi; rule_set_versions aynı şemayı taşır), §5 (yeni tablolar + package/ratification state'leri), §6 (6.11 amendment kuralının "yeni package" modeliyle güncellenmesi); AGENTS özet.
