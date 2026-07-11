# Program Haritası — Berke/Yusuf Paralel Çalışma Protokolü

> **Durum:** Koordinasyon dokümanı (canlı) — 2026-07-11
> **Kaynak masterlar:** [m4trust_stratejik_domain_evrimi_programi_v2.md](m4trust_stratejik_domain_evrimi_programi_v2.md) · [m4trust_moka_contract_faithful_payment_refactor_plan.md](m4trust_moka_contract_faithful_payment_refactor_plan.md)
> **Child planlar:** `plans/done/00_*.md` … `plans/done/05_*.md` (uygulandı) · `plans/ready/06_*.md` … `09_*.md` — her biri bağımsız uygulanabilir, sırası aşağıda.
> **Bağlayıcı kararlar (2026-07-10, ekip):** Demo öncesi yalnız **00 (H0) + 01 (Moka M0-M1, additive yan panel)** yapılır; Moka funding-unit cutover'ı (M2/M3) **package-tabanlıdır** ve Program 04'ten sonra gelir (06). Eski `moka_cüzdan_entegrasyonu.md` ödeme yolu anlatısı, Moka contract planıyla **supersede** edilmiştir.
> **Revizyon (2026-07-10, koordinasyon review'u sonrası):** (1) **Account funding 04'te YAPILMAZ** — çift ratification sonrası işlem `funding_pending` kalır, ilk gerçek funding 06'dadır; "funding exactly once" kabulü 06'ya taşındı. (2) `LEGACY_CAPABILITY_ACCESS_ENABLED` default-false cutover'ı ve tam senaryo fixture göçü 04'ten **06'ya taşındı** (v2 §2.2 Wave-3 ifadesinden bilinçli sapma; gerekçe: account evidence 05'te, funding/settlement 06'da geliyor — 04'te account ödeme senaryosu uçtan uca koşamaz). (3) **Genel kural:** Yusuf router/middleware/handler MODÜLÜ üretir; `main.py`/app-factory kaydını her wave'de Berke'nin küçük integration commit'i yapar. (4) `FakePaymentGateway` request'ler arası state korumak için 06'da SQLite-backed store'a bağlanır. (5) **Görev dağılımı ince ayarı:** 05 evidence ingestion Yusuf'a geçti (v2 §10.1 "verification lead" ile uyum; Berke 05'te bundle + settlement hook'larını alır ve 6A'ya erken başlar); 4F ikiye bölündü (rule-revision endpoint'leri = Berke — kendi 4A dosyaları; review resolution = Yusuf); `transaction_state.py` kontratını 02'de Yusuf yazar, implementasyon 03'ten itibaren Berke'dedir; ortak `tests/conftest.py`'nin tek sahibi Yusuf'tur.
> **Wave A kapanışı (2026-07-11):** 4A + 4B feature commit'leri PR #33 ile master'a taşındı; `integration/plan-04-wave-a-close` kapanışında migration `010` registry, reviews app wiring, validator→review, participant confirm→reconciliation ve approvals/evidence current-rule seam entegrasyonları tamamlandı. Wave A gate yeşildir; **Wave B ancak bu kapanıştan sonra başlar.**
> **Wave B kapanışı (2026-07-11):** 4C PR #35, 4D PR #36, 4E PR #37 ve 4F-1/4F-2 PR #38/#39 `program/domain-evolution-v2`'ye merge edildi. `integration/plan-04-close` üzerinde migration `012` registry/alias, ratifications app wiring, gerçek app ratification/funding gate’i ve Plan 04 doc-sync tamamlandı. Plan 04 kapanmıştır.

> **Plan 05 kapanışı (2026-07-11):** `integration/plan-05-close` üzerinde migration `013-014` registry, evidence/dispute app wiring, first-class account evidence settlement adapter'ı, video→review hook'u, review/dispute release guard'ı ve 5C read-only bundle/explicit snapshot semantiği tamamlandı. 015-017 erken 6A persistence kodu Plan 06 app cutover'ını bekler; sıradaki child plan 06'dır.

## 1. Uygulama sırası ve bağımlılık zinciri

```
DEMO ÖNCESİ (master'a PR, her an demo-çalışır master):
  00_delivery_authorization_hotfix      ← uygulandı: teslimat kanıtı yetkilendirmesi
  01_moka_contract_mock_and_client      ← uygulandı: contract-faithful HTTP yan paneli
  → demo freeze (yalnız hata düzeltmesi)

DEMO SONRASI (program/domain-evolution-v2 integration branch'i):
  02_foundation_migration_db_api_ci     ← uygulandı: `plans/done/02_foundation_migration_db_api_ci.md`
  03_identity_legal_entity_party_onboarding ← uygulandı: `plans/done/03_identity_legal_entity_party_onboarding.md`
  04_rule_versioning_ratification_manual_review   ← tamamlandı: Wave A + Wave B + kapanış entegrasyonu
  05_evidence_dispute_lifecycle                   ← tamamlandı: 013-014 + evidence/dispute/release integration gate
  06_milestone_funding_units_settlement ← Moka M2+M3 (package-tabanlı cutover)
  07_payment_lifecycle_operational_hardening
  08_frontend_vertical_slices           ← 03'ten itibaren kısmen paralel yürüyebilir
  09_privacy_provenance_production_readiness
```

Sıra bağlayıcıdır: bir child plan, bağımlılığı `done/` olmadan `/plan-uygula` edilmez. İstisna: 08'in Slice 1'i, 03 bitince başlayabilir (API contract frozen olduğu sürece).

## 2. Branch protokolü

- **master**: her an yeşil ve demo-çalışır. 00 ve 01 doğrudan master'a PR olur.
- **program/domain-evolution-v2**: demo freeze bitince master'dan açılır. 02+ tüm feature branch'leri buradan açılır ve buraya merge olur. Her child plan tamamlandığında (gate yeşil + doc-sync) program branch'i master'a merge edilir.
- **Feature branch ömrü 1-3 gün, tek work package.** Yeni wave branch'i her zaman güncel integration HEAD'inden açılır. Merge öncesi integration branch rebase/merge alınır.
- Migration dosyası merge sonrası **değiştirilmez**; düzeltme yeni migration ile gelir.

Branch adları child planlarda tek tek verilmiştir; kalıp: `hotfix/h0-*` (00) · `feat/moka-*` (01, 06, 07) · `feat/foundation-*` (02) · `feat/identity-*`, `feat/participants-*` (03) · vb.

## 3. Hot-file sahipliği (v2 §10.2 + Moka planı birleştirilmiş)

| Alan | Tek sahip |
|---|---|
| `db.py` → `db/` paketi, migration runner, migrations | Berke |
| `routers/transactions.py` refactor/cutover | Berke |
| `routers/approvals.py` → ratification cutover | Yusuf |
| `services/settlement.py` + ReleaseCoordinator | Berke |
| Mevcut `decision.py` semantiği | Berke (review) — yeni saf evaluator Yusuf |
| Moka contract yüzeyi: `payments/__init__.py` · `moka/contracts.py` · `moka/errors.py` · `tests/fixtures/moka/**` | Yusuf — M0 merge'i sonrası `contracts.py` + `errors.py` **frozen**; yeni hata kodu/alan = iki taraf onaylı ortak contract PR'ı |
| Moka client tarafı: `payments/ports.py` · `payments/domain.py` · `moka/{authentication,serialization,client,mapper,redaction}.py` | Berke (mapper `errors.py`'yi yalnız import eder, değiştirmez) |
| Mock Moka server (`backend/mock_moka/*`) | Yusuf |
| PaymentGateway port + FundingCoordinator + ledger/persistence | Berke |
| participants/invitations/audit/review/**evidence**/dispute servisleri | Yusuf (v2 §10.1 verification lead) |
| Legacy router'lar (`routers/delivery.py`, legacy party/manager-view yolları) | Berke — 05 sonrası fiilen donuk |
| `tests/conftest.py` + ortak test-infra | Yusuf — domain fixture'larını herkes KENDİ ayrı modülünde tutar, conftest'e yalnız Yusuf commit atar |
| `.env.example` | Berke (config sahibi) — Yusuf ihtiyaçlarını PR'da işaretler, Berke işler |
| `services/access_control.py` + ActorContext | Berke — Yusuf taraf-özel kontrolleri kendi servis modüllerinde yazar, bu dosyaya dokunmaz |
| `code/frontend/**` (vite.config + `/api` proxy dahil) | Yusuf — Berke yalnız backend static-serve kararı + PR review |
| `main.py`, `config.py`, requirements manifestleri | Berke (integration lead) — router/middleware/handler kayıtları dahil (Revizyon #3 genel kuralı) |
| ARCHITECTURE.md / AGENTS.md doc-sync | Berke, integration checkpoint'te (iki branch'te eşzamanlı doc-sync YASAK) |

## 4. Migration numara rezervasyonu (child planlar bu tabloyu esas alır)

v2 §10.4 rezervasyonu, Moka planının supersede'leriyle şu şekilde güncellenmiştir (henüz hiç migration yazılmadığı için bu bir revizyondur, renumbering değildir):

```
001_baseline_current_schema           Berke  (02)  ← bugünkü init_db() çıktısının TAMAMI
002  (rezerve, kullanılmadı)
003_identity_sessions                 Berke  (03)
004_legal_entities_memberships        Berke  (03)
005_participants_invitations          Yusuf  (03)
006_audit_events                      Yusuf  (03)
007_transaction_lifecycle_v2          Berke  (03)  ← created_by/owner_entity/lifecycle_version/content_sha256
008_documents_extraction_runs         Berke  (04)
009_rule_set_versions                 Berke  (04)
010_review_cases                      Yusuf  (04)
011_ratification_packages             Berke  (04)  ← v2'deki 011_tracking_policy_versions yerine
                                                     (policy, package içinde SNAPSHOT olarak taşınır;
                                                      versioned policy tablosu 09'a ertelendi)
012_ratifications                     Yusuf  (04)
013_evidence_records                  Yusuf  (05)
014_disputes                          Yusuf  (05)
015_milestones                        Berke  (06)
016_funding_units_provider_payments   Berke  (06)  ← v2 "mock_ledger_v2" SUPERSEDED (Moka §24)
017_release_instructions              Berke  (06)
018_processing_jobs                   Berke  (07)
019_tracking_policy_versions          Berke  (09)
020_document_storage_references       Berke  (09)
021_auth_verification_reset_tokens    Yusuf  (09)
022_extraction_provenance_extensions  Yusuf  (09)
```

`payment_attempts` tablosu **yoktur**: Moka planındaki `provider_operations` (attempt_no'lu) aynı işi görür; v2 §5.20 bu kararla supersede edilir.

## 5. Donmuş interface takvimi

| Interface | Freeze anı | Tanım |
|---|---|---|
| `PaymentGateway` + `contracts.py` DTO'ları + `ProviderCapabilities` | 01 / M0 sonu | Moka §6, §5.1 |
| `ActorContext` + error envelope + `get_db` dependency + migration contract + `get_current_actor` dependency ve `require_authenticated_user`/`require_active_membership` imzaları | 02 sonu | v2 §6.1, Wave 0 freeze — 03/3B bunlara karşı kodlar (testte `dependency_overrides` + StubActor) |
| `ParticipantService` | 03, Faz 3C'den önce | v2 §8.1 |
| `RuleVersionService` + `ReviewService` | 04 Wave A başında | v2 §8.2-8.3 |
| `MilestoneDraft`/`FundingUnitDraft`/`compile_funding_plan` | 04 Faz 4C başında | Moka §9 |
| `RatificationPackageService` + `FundingCoordinator` | 04 Wave B başında | v2 §8.4-8.5 |
| `EvidenceService` | 05 başında | v2 §8.6 |
| `MilestoneEvaluator`/`MilestoneDecision`/`ReleaseCandidate` | 06 başında | v2 §8.8-8.9, Moka §19 |

## 6. Aynı anda yapılmayacaklar (v2 §12 + Moka birleşik)

1. İki kişi `transactions.py` veya migration runner dosyalarını değiştirmez.
2. Approval cutover ile package contract aynı branch'te geliştirilmez.
3. Milestone evaluator `settlement.py` içine yazılmaz.
4. Funding-unit persistence (016) gelmeden multi-milestone settlement merge edilmez.
5. Legacy capability removal, Wave 3 account E2E yeşil olmadan yapılmaz.
6. ARCHITECTURE/AGENTS iki branch'te eşzamanlı güncellenmez.
7. `ExtractionJSON` hiçbir child plan tarafından değiştirilmez/genişletilmez.
8. `contracts.py` M0 freeze'inden sonra tek taraflı değiştirilmez.
9. Review bypass geçici çözüm olarak approval/ratification path'ine eklenmez.
10. GET endpoint'lere yeni side-effect eklenmez.

## 7. İş yükü dengeleme — kimse beklemez

Wave içi kritik yol hep tek kişide toplanmasın diye boş-zaman kuralları:

| An | Berke | Yusuf |
|---|---|---|
| 02 | 2A (kritik yol: migration runner + get_db) | 2B + `transaction_state` kontratı |
| 03 / 3C sırasında | ownership cutover | **08/8A frontend foundation'a başlar** (3A merge'i yeterli) |
| 04 Wave B | 4D + 4F-1 (rule-revision uçları) | 4C → 4E → 4F-2 (review resolution) |
| 05 | 5C + settlement hook commit'leri + **6A'ya erken başlangıç** (6A persistence işi 05'e bağımlı değil) | 5A → 5B (kendi domain'i, sıralı) |
| 07 | 7A | 7B → biter bitmez 08 slice'larına döner |

## 8. Her PR'da (kısa checklist — tam liste v2 §13)

```
[ ] Child plan maddesi referansı        [ ] Full suite yeşil (baseline 214+)
[ ] Migration additive + smoke          [ ] ExtractionJSON değişmedi
[ ] decision.py saf / settlement tek guard
[ ] Token/PII event-audit-log sızıntı kontrolü
[ ] Legacy (lifecycle_v1) davranışı bozulmadı
[ ] Doc-sync ihtiyacı işaretlendi (yalnız integration checkpoint'te uygulanır)
```
