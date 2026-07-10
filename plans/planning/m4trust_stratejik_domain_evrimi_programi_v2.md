# M4Trust Stratejik Domain Evrimi Programı v2

> **Durum:** Güçlendirilmiş master plan — 2026-07-10  
> **Repository baseline:** `8be46d12301329188cadc19fc8139863845ce301` (`fix 2`)  
> **Doğrulanan baseline:** `cd code && pytest` → **214 passed**  
> **Review girdisi:** `review.md` — kod tabanıyla karşılaştırmalı inceleme  
> **Önerilen repository yolu:** `plans/planning/m4trust_stratejik_domain_evrimi_programi_v2.md`  
> **Program türü:** Çok aşamalı domain evrimi, güvenlik sertleştirmesi ve ürünleştirme programı  
> **Uygulama biçimi:** Tek dev task değildir; bağımlılık sıralı child planlar ve kısa ömürlü paralel workstream'ler  
> **Ana hedef:** M4Trust'ın mevcut anonim capability-link tabanlı demo çekirdeğini; kimliği, temsil ilişkisi, versiyonlu onayı, recoverable review akışı, first-class kanıtları, insan kontrollü uyuşmazlığı, milestone bazlı ödeme yürütmesi ve idempotent ödeme yaşam döngüsü olan denetlenebilir B2B şartlı ödeme platformuna dönüştürmek.

---

# 1. Yönetici özeti

M4Trust'ın mevcut backend çekirdeği sağlam bir güven sınırına sahiptir:

- LLM ödeme kararı vermez.
- Deterministik validator güvenlik kapısıdır.
- İnsan onayı olmadan ödeme akışı ilerlemez.
- Takip politikası onay öncesi kilitlenir.
- Sözleşmesel kanıt gereksinimleri yönetici tercihiyle zayıflatılamaz.
- Video tek başına miktar, release oranı veya dispute üretmez.
- `decision.py` saf fonksiyondur.
- Release guard `settlement.py` içinde tek yerde yaşar.
- Dış servisler adapter + fake/mock çifti arkasındadır.
- `ExtractionJSON` benchmark ve LLM hattı için donmuş sözleşmedir.

Mevcut sistemin ana eksiği tek bir endpoint veya tablo değildir. Eksik olan, güvenilir ve sürdürülebilir bir **işlem yaşam döngüsüdür**.

Bugünkü akış:

```text
anonim upload
→ extraction
→ validator
→ manager capability ile tracking policy
→ buyer/seller capability ile onay
→ tek pool payment
→ transaction-level kanıt
→ transaction-level tek karar
```

Hedef akış:

```text
authenticated user
→ temsil ettiği legal entity
→ işlem sahipliği
→ contract document version
→ extraction run
→ immutable rule-set version
→ participant onboarding
→ party reconciliation
→ tracking policy version/snapshot
→ canonical ratification package
→ user + entity + package-bound ratification
→ funding
→ executable milestones
→ first-class evidence
→ deterministic milestone evaluation
→ review / human-controlled dispute
→ idempotent release instructions
→ provider confirmation
→ tam audit ve provenance
```

Bu programın temel stratejik sonucu şudur:

> Identity, party onboarding, rule versioning, ratification, review, evidence, milestone ve payment lifecycle birbirinden bağımsız feature'lar değildir. Aynı güven zincirinin sıralı katmanlarıdır.

---

# 2. Review sonrası bağlayıcı kararlar

Bu bölüm önceki plandaki belirsizlikleri ve review tarafından tespit edilen çelişkileri kesin karara bağlar.

## 2.1 Regression tanımı

“Mevcut testler korunur” ifadesi artık şu anlama gelir:

> Mevcut **iş senaryolarının, güvenlik ilkelerinin ve karar semantiğinin** regression kapsamı korunur. Eski anonim endpoint contract'ları ve capability tabanlı fixture'lar kalıcı sözleşme değildir; Wave 3 cutover'ında account-based fixture'lara taşınabilir.

Korunacak semantik:

- İki taraf onayı olmadan funding olmaz.
- Policy kilitlenmeden ratification olmaz.
- Sözleşmesel kanıt eksikse release olmaz.
- Optional video yokluğu bloklamaz.
- Yüksek güvenli video anomalisi hold/manual review üretir.
- Video otomatik dispute üretmez.
- Approval-only senaryo tam release olabilir.
- Kısmi teslim semantiği kaybolmaz.
- Aynı ödeme iki kez uygulanmaz.
- Public projection hassas veri sızdırmaz.

Korunması zorunlu olmayan legacy API biçimi:

```text
POST /api/transactions  # anonim
buyer_token
seller_token
manager_token
token query/body tabanlı kalıcı erişim
```

## 2.2 Legacy erişim cutover'ı

Legacy davranış sonsuza kadar feature flag arkasında tutulmayacaktır.

Geçiş:

```text
Wave 0-2:
- eski transaction'lar legacy mode
- yeni geliştirme account mode
- legacy regression fixture'ları çalışabilir

Wave 3:
- ratification cutover
- scenario testleri account-based fixture'a taşınır
- LEGACY_CAPABILITY_ACCESS_ENABLED default false

Program sonu:
- legacy capability route/kolon removal planı
```

Yeni anonim transaction oluşturma mümkün olduğunca erken kapatılır. Eski testler gerektiğinde doğrudan legacy fixture/factory ile hazırlanır.

## 2.3 Milestone ile kısmi teslim semantiği

Bugünkü sistem transaction seviyesinde:

```text
capture_ratio =
delivered_quantity / total_contract_quantity
```

hesabı yapmaktadır. `payment_rules[].percentage` ve `trigger` henüz execution matematiğinde kullanılmamaktadır.

Milestone dünyasında iki ayrı oran vardır:

```text
milestone_share
= milestone'un sözleşme toplamındaki payı

milestone_completion
= milestone içinde doğrulanmış teslim/iş oranı
```

Örnek:

```text
contract total: 100,000 TRY
delivery milestone: 40% = 40,000 TRY
verified delivery: 50%
eligible cumulative release: 20,000 TRY
```

Her milestone açık bir release policy taşır:

```text
release_mode:
- all_or_nothing
- proportional_to_verified_quantity
```

Kurallar:

- LLM tek başına release mode belirleyemez.
- Compiler deterministik default önerebilir.
- Mode ratification package içinde görünür.
- Taraflar bu mode'u onaylar.
- Legacy teslimat senaryosu compatibility amacıyla
  `proportional_to_verified_quantity` kullanabilir.

Cumulative kısmi release hesabı:

```text
target_released_minor =
floor(
    milestone_amount_minor
    * cumulative_verified_quantity
    / contract_quantity
)

release_now =
target_released_minor - already_released_minor
```

Tam tamamlanmada rounding remainder'ın tamamı release edilir.

Milestone tutarlarının toplam contract amount'a dağıtımında deterministic largest-remainder yöntemi kullanılır.

## 2.4 Migration baseline kararı

Migration `001` şu anki **tam `init_db()` çıktısını** temsil eder:

- transactions,
- manager_token,
- extracted_rules,
- approvals,
- events,
- mock_payments,
- evidence,
- tracking_policies.

Ayrı `002_tracking_policy_existing` migration'ı yoktur.

## 2.5 Migration bootstrap/stamping

Runner üç durumu ayırmak zorundadır:

```text
A. Tamamen boş DB
→ schema_migrations oluştur
→ 001 ve devamını uygula

B. Bilinen legacy şema, schema_migrations yok
→ schema fingerprint doğrula
→ 001'i applied olarak stamp et
→ sonraki migration'ları uygula

C. Kısmi veya bilinmeyen şema
→ fail closed
→ otomatik mutation yapma
→ açık diagnostic üret
```

Legacy fingerprint:

- required table names,
- required columns,
- manager_token varlığı,
- tracking_policies kolonları

üzerinden doğrulanır.

Stamping veri üretmez, tabloyu yeniden oluşturmaz ve baseline migration SQL'ini çalıştırmaz.

## 2.6 SQLite concurrency kararı

Her connection:

```text
sqlite3.connect(..., timeout=5.0)
PRAGMA busy_timeout=5000
PRAGMA journal_mode=WAL
PRAGMA foreign_keys=ON
```

uygular.

Ek kurallar:

- Session `last_seen_at` her istekte yazılmaz.
- Yalnız son yazımdan en az 60 saniye geçmişse güncellenir.
- Invitation accept, ratification ve release creation kısa DB transaction'ı içinde yürür.
- Kritik write yarışlarında DB unique constraint source of truth'tur.
- Gerektiğinde `BEGIN IMMEDIATE` kullanılır.
- Yalnız SQLite lock hatası sınırlı retry alabilir.
- Business validation/auth hataları retry edilmez.

## 2.7 Mock provider çoklu release ön koşulu

Mevcut mock provider:

- yalnız `status == pool` iken approve eder,
- ilk partial release sonrası `partially_released` olur,
- ikinci release'i desteklemez.

Bu nedenle multi-milestone settlement, minimal Mock Ledger v2 olmadan entegre edilmeyecektir.

Sıra:

```text
1. Saf milestone compiler/evaluator
2. Mock Ledger v2 minimum:
   pool_amount_minor
   released_amount_minor
   remaining_amount_minor
   multi-release
3. Multi-milestone settlement integration
4. Gelişmiş retry/reconcile/webhook lifecycle
```

## 2.8 State migration kararı

Legacy state'ler destructive migration ile yeni state'lere çevrilmez.

Transaction:

```text
lifecycle_version:
- legacy_v1
- account_v2
```

veya eşdeğer `access_mode/lifecycle_version` alanı taşır.

Legacy satırlar eski state'lerini korur. Canonical projection adapter kullanır.

| Legacy state | Canonical görünüm |
|---|---|
| uploaded | processing |
| extracting | processing |
| awaiting_review | preparation / blocked_review |
| awaiting_approval | preparation / ready_for_ratification |
| rejected | rejected |
| active | active |
| evidence_pending | active / blocked_evidence |
| decided + fully released | settled |
| decided + partially released | active / partially_settled |

Yeni `account_v2` transaction'lar yeni state machine'i kullanır.

## 2.9 CI dependency kararı

Tek ağır `requirements.txt` doğrudan CI'a kurulmaz.

Hedef:

```text
requirements-core.txt
requirements-ci.txt
requirements-rag.txt
requirements-video.txt
```

veya eşdeğer `pyproject.toml` extras.

`requirements-ci.txt`:

- FastAPI,
- Pydantic,
- httpx,
- pytest,
- parser testleri için gerekli hafif paketler,
- argon2-cffi,
- lint/type-check araçları

içerir.

RAG/torch bağımlılıkları ayrı job veya manuel integration profile'da çalışır.

## 2.10 DB connection lifecycle kararı

Request router'ları ortak request-scoped DB dependency kullanır.

```text
get_db()
→ open
→ yield
→ success commit
→ exception rollback
→ close
```

Background tasks kendi bağımsız connection'ını açar.

Business event ve audit event aynı connection/transaction içinde yazılır.

## 2.11 Document storage ve hash kararı

Orijinal upload temp file pipeline sonunda silindiği için:

- SHA-256 upload bytes okunurken hesaplanır.
- Program 2A öncesinde `DocumentStorageProvider` contract'ı dondurulur.
- Demo/local implementasyon filesystem olabilir.
- `contract_documents.storage_ref` kalıcı referans taşır.
- Temp file tek source of truth değildir.

## 2.12 Evidence bundle side-effect kararı

`GET` endpoint veri yazmaz.

Hedef:

```text
GET /evidence-bundle
→ mevcut state'ten saf bundle üretimi

POST /evidence-snapshots
→ explicit immutable snapshot oluşturma
```

Snapshot:

- package/state/hash ile idempotent,
- audit event üretir,
- tekrar GET edilmesi yeni DB satırı üretmez.

## 2.13 Session/frontend taşıma kararı

Development:

```text
Vite dev server
→ /api proxy
→ FastAPI
→ same-origin browser görünümü
```

Production:

```text
SPA + API same-origin
```

Frontend:

```text
fetch(..., credentials="include")
```

Session cookie:

- HttpOnly,
- SameSite=Lax,
- production'da Secure,
- CSRF/Origin korumalı.

## 2.14 PII risk kararı

Legal entity TCKN/VKN alanı şifrelenirken mevcut:

- `transactions.markdown`,
- `extracted_rules.extraction_json`

ham PII içerebilir.

Bu tutarsızlık gizlenmez.

Aşamalar:

```text
Hackathon/local demo:
- kabul edilmiş risk
- production-ready claim yok
- public projection maskeli
- erişim kısıtlı

Hardening hedefi:
- encrypted document storage
- raw extraction retention policy
- identity fields ayrıştırma
- key management
```

## 2.15 Canonical hash kararı

Hash her okumada Python object'inden yeniden üretilmez.

```text
canonical_payload_json = stable UTF-8 JSON string
package_hash = sha256(canonical_payload_json bytes)
```

- Canonical string bir kez oluşturulup saklanır.
- Hash saklanan byte'lar üzerinden hesaplanır.
- Read-time integrity check isteğe bağlı yapılabilir.

## 2.16 Awaiting review phase boundary

Bugünkü `awaiting_review` recoverable değildir.

Program 2 rule revision gelene kadar:

- full E2E fixture'ları PASS sözleşmeler kullanır,
- NEEDS_REVIEW yalnız blocked-state olarak test edilir,
- ileri geçiş beklenmez.

Yarım bir review bypass Program 1'e sokulmaz.

---

# 3. Programdan önce uygulanacak acil hardening patch

Bu iş büyük programı beklememelidir.

## H0 — Unauthorized evidence/release kapatma

### Sorun

Bugün:

```text
GET /api/transactions
→ auth yok
→ transaction IDs görünür

POST /api/transactions/{id}/events/e-irsaliye
→ auth/token yok
→ active transaction'a teslim quantity gönderilebilir
→ settlement tetiklenir
```

Mock para olsa bile gerçek finansal sistemde kabul edilemez bir desendir.

### H0 kapsamı

1. E-irsaliye endpoint seller veya manager capability ister.
2. Video endpoint seller veya manager capability ister.
3. Buyer kendi lehine teslimat kanıtı sunamaz.
4. Token event/log/evidence içine girmez.
5. Public transaction listesi:
   - `DEMO_PUBLIC_DASHBOARD=true` ise açık,
   - default kapalı veya manager capability gerektirir.
6. `busy_timeout=5000`.
7. Stale approvals docstring düzeltmesi.
8. AGENTS test count 214'e güncellenir.
9. Authorization regression testleri eklenir.

### H0 kabul kriterleri

- Anonymous e-irsaliye → 403.
- Buyer token e-irsaliye → 403.
- Seller token e-irsaliye → allowed.
- Manager token e-irsaliye → allowed.
- Anonymous video → 403.
- Token hiçbir event/evidence payload'ında yok.
- Demo public dashboard env off iken liste erişimi kapalı.
- Mevcut karar semantiği korunur.
- Full suite yeşil.

H0 ayrı plan/commit olmalıdır:

```text
plans/done/00_delivery_authorization_hotfix.md
```

---

# 4. Mevcut kod tabanından korunan sınırlar

## 4.1 `decision.py` saf kalır

- DB bilmez.
- HTTP bilmez.
- Provider bilmez.
- User/auth bilmez.
- Event emit etmez.

Yeni milestone evaluator da saf modüldür.

## 4.2 `settlement.py` tek release guard sahibi kalır

Router:

- evidence kabul eder,
- ratification kaydeder,
- review action alır.

Ancak release kararını ve provider submission'ı kendisi yapmaz.

## 4.3 `ExtractionJSON` değişmez

Identity, participant, policy version, package, milestone gibi platform kavramları extraction şemasına eklenmez.

## 4.4 Adapter + fake/mock korunur

Yeni dış bağımlılıklar:

```text
NotificationProvider
IdentityVerificationProvider
DocumentStorageProvider
PaymentProvider
```

adapter arkasında yaşar.

## 4.5 Otomatik dispute yok

LLM, validator, video:

- finding,
- hold,
- review recommendation

üretebilir.

Dispute yetkili insan eylemidir.

---

# 5. Hedef domain modeli

## 5.1 User

```text
users
- id
- email_normalized
- password_hash
- first_name
- last_name
- phone_ciphertext nullable
- status active|disabled
- email_verified_at nullable
- created_at
- updated_at
```

Constraint:

```text
UNIQUE(email_normalized)
```

## 5.2 Session

```text
sessions
- id
- user_id
- token_hash
- csrf_token_hash
- expires_at
- revoked_at
- created_at
- last_seen_at
```

Kurallar:

- random token,
- DB'de hash,
- session rotate/revoke,
- throttled last_seen update.

## 5.3 Legal entity

```text
legal_entities
- id
- entity_type individual|company
- legal_name
- tax_identifier_type tckn|vkn
- tax_identifier_ciphertext
- tax_identifier_lookup_hmac
- tax_identifier_last4
- tax_office nullable
- address_json nullable
- verification_status self_declared|pending|verified
- created_by_user_id
- created_at
- updated_at
```

## 5.4 Membership

```text
memberships
- id
- user_id
- legal_entity_id
- role owner|admin|member
- status active|revoked
- created_at
```

Constraint:

```text
UNIQUE(user_id, legal_entity_id)
```

## 5.5 Transaction participant

```text
transaction_participants
- id
- transaction_id
- role buyer|seller
- legal_entity_id nullable
- status invited|profile_incomplete|ready|confirmed
- extracted_snapshot_json
- declared_snapshot_json
- confirmed_snapshot_json
- confirmed_at nullable
- created_at
- updated_at
```

Constraint:

```text
UNIQUE(transaction_id, role)
```

## 5.6 Transaction assignment

```text
transaction_assignments
- id
- transaction_id
- participant_id nullable
- user_id
- legal_entity_id
- role manager|approver|viewer
- status active|revoked
- created_at
```

## 5.7 Invitation

```text
transaction_invitations
- id
- transaction_id
- participant_role
- invited_email_normalized
- token_hash
- expires_at
- status pending|opened|accepted|expired|revoked
- created_by_user_id
- accepted_by_user_id nullable
- accepted_at nullable
- revoked_at nullable
- created_at
```

## 5.8 Contract document

```text
contract_documents
- id
- transaction_id
- version
- original_filename
- media_type
- storage_ref
- content_sha256
- normalized_markdown_sha256
- uploaded_by_user_id
- status active|superseded
- created_at
```

## 5.9 Extraction run

```text
extraction_runs
- id
- transaction_id
- document_id
- provider
- model
- prompt_version
- schema_version
- rag_provenance_json
- privacy_summary_json
- extraction_json
- status ok|needs_review|failed
- failure_reason nullable
- created_at
```

Raw model sonucu immutable kalır.

## 5.10 Rule-set version

```text
rule_set_versions
- id
- transaction_id
- version
- parent_version_id nullable
- source_extraction_run_id nullable
- rules_json
- rules_hash
- validator_status
- validator_report_json
- status draft|validated|ratifiable|superseded|ratified
- created_by_user_id nullable
- created_by_actor_type user|system
- created_at
```

## 5.11 Tracking policy version

```text
tracking_policy_versions
- id
- transaction_id
- version
- recommendation
- recommendation_reason_codes_json
- physical_delivery_confirmed
- tracking_mode
- video_role
- status draft|locked|superseded
- configured_by_user_id
- locked_by_user_id
- configured_at
- locked_at
```

Geçişte mevcut tablo korunup package snapshot kullanılabilir. Nihai hedef versioned tablodur.

## 5.12 Ratification package

```text
ratification_packages
- id
- transaction_id
- version
- document_id
- rule_set_version_id
- tracking_policy_version_id nullable
- canonical_payload_json
- document_hash
- rule_set_hash
- participant_snapshot_hash
- tracking_policy_hash
- package_hash
- status draft|open|complete|superseded|cancelled
- created_at
- opened_at nullable
- completed_at nullable
```

## 5.13 Ratification

```text
ratifications
- id
- package_id
- transaction_id
- participant_id
- user_id
- legal_entity_id
- participant_role
- auth_method session|demo_seed
- approved_at
- client_ip_hash nullable
- user_agent_summary nullable
```

Constraint:

```text
UNIQUE(package_id, participant_id)
```

## 5.14 Review case

```text
review_cases
- id
- transaction_id
- phase pre_ratification|settlement|payment
- source_type validator|party_mismatch|evidence|video|payment|system
- source_id nullable
- reason_code
- title
- description
- severity warning|blocking
- status open|evidence_requested|resolved|escalated|cancelled
- assigned_to_user_id nullable
- opened_by_actor_type
- opened_by_user_id nullable
- resolved_by_user_id nullable
- resolution_code nullable
- resolution_note nullable
- created_at
- resolved_at nullable
```

## 5.15 Review action

```text
review_actions
- id
- review_case_id
- actor_user_id
- acting_entity_id
- action
- payload_json
- created_at
```

## 5.16 Evidence record

```text
evidence_records
- id
- transaction_id
- milestone_id nullable
- evidence_type contract|e_irsaliye|video|e_invoice|other
- source upload|external_api|analyzer|system
- submitted_by_user_id
- submitted_by_entity_id
- external_reference nullable
- storage_ref nullable
- file_sha256 nullable
- payload_json
- verification_status received|verified|rejected|review_required
- analyzer_provider nullable
- analyzer_version nullable
- created_at
- verified_at nullable
```

## 5.17 Dispute

```text
disputes
- id
- transaction_id
- milestone_id nullable
- opened_by_user_id
- opened_by_entity_id
- reason_code
- description
- status open|awaiting_response|evidence_requested|under_review|resolved|cancelled
- resolution_code nullable
- resolved_by_user_id nullable
- created_at
- resolved_at nullable
```

## 5.18 Milestone

```text
milestones
- id
- transaction_id
- ratification_package_id
- rule_set_version_id
- rule_index
- title
- trigger_type
- percentage_basis_points
- amount_minor
- currency
- required_evidence_json
- release_mode all_or_nothing|proportional_to_verified_quantity
- status pending|evidence_pending|eligible|held|release_pending|partially_released|released|disputed|cancelled
- released_amount_minor
- created_at
- updated_at
```

## 5.19 Release instruction

```text
release_instructions
- id
- transaction_id
- milestone_id
- amount_minor
- currency
- idempotency_key
- status created|submitted|confirmed|failed|reversed|refunded
- provider
- provider_reference nullable
- created_at
- updated_at
```

## 5.20 Payment attempt

```text
payment_attempts
- id
- release_instruction_id
- attempt_no
- request_fingerprint
- provider_response_json
- status
- error_code nullable
- created_at
```

## 5.21 Audit event

```text
audit_events
- id
- transaction_id nullable
- actor_type user|system|provider
- actor_user_id nullable
- acting_entity_id nullable
- action
- target_type
- target_id
- request_id
- metadata_json
- created_at
```

---

# 6. Authorization modeli

## 6.1 ActorContext

```text
ActorContext
- actor_type
- user_id
- acting_entity_id
- platform_role
- transaction_assignment_role
- participant_role
- request_id
- auth_method
```

## 6.2 Merkezi access control

```text
services/access_control.py
```

Fonksiyonlar:

```text
require_authenticated_user
require_active_membership
require_transaction_access
require_transaction_manager
require_participant_approver
require_platform_reviewer
require_evidence_submitter
```

## 6.3 Aynı taraf / conflict kuralları

- Aynı legal entity buyer ve seller olamaz.
- Aynı user iki taraf adına ratification veremez.
- Creator counterparty invitation'ı kabul edemez.
- Participant approver yalnız kendi participant/entity adına hareket eder.
- Platform reviewer ticari taraf olarak ratification vermez.

---

# 7. State modeli

## 7.1 Account v2 top-level state

```text
draft
processing
preparation
awaiting_ratification
funding_pending
active
settled
cancelled
rejected
```

## 7.2 Alt state'ler ayrı kaynaklardadır

- invitation status,
- participant status,
- rule-set status,
- review status,
- package status,
- milestone status,
- payment status.

## 7.3 Derived readiness

```text
ready_for_ratification =
    current_rule_set.validator_status == PASS
    AND buyer.status == confirmed
    AND seller.status == confirmed
    AND tracking_policy.status == locked
    AND no_blocking_pre_ratification_review
```

```text
ready_for_funding =
    current_package.status == complete
    AND current_package_is_latest
    AND buyer_ratified
    AND seller_ratified
    AND no_blocking_review
```

## 7.4 State transition servisi

```text
transition_transaction(
    transaction_id,
    expected_states,
    target_state,
    actor_context,
    reason
)
```

`transactions.version` optimistic concurrency counter alır.

---

# 8. Donmuş interface'ler

Paralel çalışmanın güvenli olması için wave başlamadan bu interface'ler yazılı olarak dondurulur.

## 8.1 ParticipantService

```python
attach_creator(
    conn,
    transaction_id,
    actor_context,
    own_role,
    legal_entity_id,
) -> Participant

create_counterparty_placeholder(
    conn,
    transaction_id,
    counterparty_role,
    extracted_snapshot,
) -> Participant

accept_invitation(
    conn,
    invitation_token,
    actor_context,
    legal_entity_id,
) -> Participant
```

## 8.2 RuleVersionService

```python
create_initial_from_extraction(...)
create_revision(...)
validate_version(...)
get_current(...)
supersede(...)
```

## 8.3 ReviewService

```python
open_case(...)
record_action(...)
resolve_case(...)
has_blocking_case(...)
```

## 8.4 RatificationPackageService

```python
build_current_package(...)
open_package(...)
supersede_if_inputs_changed(...)
get_current(...)
verify_integrity(...)
```

## 8.5 FundingCoordinator

```python
ensure_pool_funded(
    conn,
    transaction_id,
    package_id,
    actor_context,
) -> FundingResult
```

Ratification router provider'ı doğrudan çağırmaz.

## 8.6 EvidenceService

```python
submit_evidence(...)
verify_evidence(...)
collect_transaction_delivery_evidence(...)
collect_milestone_evidence(...)
```

## 8.7 MilestoneCompiler

```python
compile_milestones(
    rule_set,
    total_amount_minor,
    currency,
    package_id,
) -> tuple[MilestoneDraft, ...]
```

## 8.8 MilestoneEvaluator

```python
evaluate_milestone(
    milestone,
    evidence_set,
    review_state,
) -> MilestoneDecision
```

## 8.9 ReleaseCoordinator

```python
create_release_candidate(...)
ensure_release_instruction(...)
submit_pending_instruction(...)
apply_provider_confirmation(...)
```

---

# 9. Program aşamaları

---

## H0 — Immediate delivery authorization hardening

Ayrı, küçük, demo öncesi uygulanabilir.

Detay §3'tedir.

---

## Program 0 — Foundation: migration, DB lifecycle, API contract, CI ve repository seams

### Amaç

Yeni feature'lardan önce iki kişinin güvenli paralel çalışabileceği temel.

### İş kalemleri

1. Migration runner.
2. Baseline fingerprint/stamping.
3. `001_baseline_current_schema`.
4. Connection factory:
   - timeout,
   - busy_timeout,
   - WAL,
   - FK.
5. Request-scoped DB dependency.
6. Background task connection helper.
7. Transaction helper/context manager.
8. Request ID middleware.
9. Ortak API error envelope.
10. Pydantic response contract'ları.
11. `ActorContext` protocol.
12. Access-control protocol.
13. Business event / audit event ayrım contract'ı.
14. Requirements manifest ayrımı.
15. GitHub Actions minimal CI.
16. Empty DB migration smoke.
17. Legacy DB stamping/upgrade smoke.
18. Unknown schema fail-closed smoke.
19. Legacy state adapter contract.
20. `transactions.py` repository seams.
21. Tracking router ayrıştırma hazırlığı.
22. Stale docstring/test-count doc-sync.

### Program 0 kabul kriterleri

- Empty DB migration tamamlar.
- Current legacy DB fingerprint ile stamp edilir.
- Bilinmeyen şema mutate edilmez.
- Migration ikinci koşuda idempotenttir.
- `busy_timeout` aktiftir.
- Request exception rollback yapar.
- Background task kendi connection'ını kullanır.
- CI ağır RAG dependency kurmaz.
- 214 scenario semantics korunur.
- H0 dahilse full suite yeşildir.
- ExtractionJSON değişmez.
- Decision/tracking semantiği değişmez.

---

## Program 1 — Identity, session, legal entity, ownership ve invitation onboarding

### Faz 1A — Auth

- register,
- login,
- logout,
- me,
- revoke session,
- password hashing,
- cookie/CSRF,
- Vite proxy contract.

### Faz 1B — Legal entities

- company/individual create,
- encrypted tax ID,
- lookup HMAC,
- last4 projection,
- memberships,
- owner/admin/member.

### Faz 1C — Authenticated transaction ownership

- `created_by_user_id`,
- `owner_entity_id`,
- `lifecycle_version=account_v2`,
- authenticated upload,
- access-scoped list/detail,
- document hash upload anında.

### Faz 1D — Participant + invitation

- creator participant,
- counterparty placeholder,
- invitation,
- FakeNotificationProvider,
- accept,
- entity select/create,
- participant profile,
- participant confirm.

### Program 1 phase boundary

`NEEDS_REVIEW` transaction ilerlemez. Bu Program 2'ye kadar beklenen davranıştır.

### Program 1 kabul kriterleri

- Anonymous create reddedilir.
- User yalnız aktif membership entity adına create eder.
- Transaction list/detail scoped'dur.
- Invitation token hashlenir.
- Wrong email/expired/reused invite reddedilir.
- Creator counterparty invite kabul edemez.
- Same entity buyer/seller olamaz.
- Actor-aware audit vardır.
- PASS fixture onboarding E2E çalışır.
- Legacy transaction compatibility adapter bozulmaz.

---

## Program 2 — Document provenance, rule versioning, reconciliation, ratification ve manual review

### Faz 2A — DocumentStorageProvider

```text
LocalDocumentStorageProvider
FutureCloudDocumentStorageProvider
```

- upload bytes hash,
- storage ref,
- document version,
- normalized markdown hash.

### Faz 2B — Extraction run provenance

- model/provider,
- prompt version,
- schema version,
- RAG source IDs,
- privacy summary.

### Faz 2C — Rule-set versions

- initial version,
- immutable revision,
- current version,
- validator per version,
- no latest-by-rowid duplication.

### Faz 2D — Party reconciliation

- extracted vs declared vs confirmed,
- mismatch codes,
- blocking review case.

### Faz 2E — Tracking policy version/snapshot

- configured/locked actor,
- package input,
- policy change supersedes package.

### Faz 2F — Canonical ratification package

- stored canonical JSON bytes/string,
- SHA-256,
- package integrity,
- participant snapshots,
- release_mode visibility.

### Faz 2G — Account ratification

- package-bound,
- user/entity/participant-bound,
- dual side,
- idempotent,
- same user cannot approve both sides.

### Faz 2H — Recoverable manual review

- revise rule,
- revalidate,
- resolve mismatch,
- request evidence,
- open new package,
- reject/cancel.

### Program 2 kabul kriterleri

- Raw extraction immutable.
- Revision yeni version üretir.
- Same canonical payload same hash.
- Any bound input change new hash.
- Hash stored canonical bytes üzerinden üretilir.
- NEEDS_REVIEW recoverable olur.
- Superseded package funding yapamaz.
- Both sides same package hash görür.
- Both ratifications olmadan funding yok.
- Funding exactly once.
- Legacy approval route default off olur.
- Scenario regression fixture'ları account mode'a taşınır.

---

## Program 3 — Evidence records, evidence bundle ve human-controlled dispute

### Faz 3A — Authorized evidence ingestion

- user/session auth,
- transaction assignment,
- submitter actor/entity,
- file/payload hash,
- external reference,
- duplicate/idempotency.

### Faz 3B — Legacy decision adapter

```text
evidence_records
→ DeliveryEvidence
→ current decision.py
```

Milestone gelmeden mevcut settlement davranışı korunur.

### Faz 3C — Review integration

- video anomaly → review case,
- invalid evidence → review,
- additional evidence request.

### Faz 3D — Dispute

- human opens,
- participant authorization,
- evidence links,
- timeline,
- hold semantics.

### Faz 3E — Evidence bundle semantics

- GET read-only,
- POST snapshot explicit,
- actor/provenance/hash,
- no raw token/secret.

### Program 3 kabul kriterleri

- Anonymous evidence rejected.
- Wrong participant rejected.
- Evidence actor/entity kayıtlı.
- Duplicate external reference idempotent/rejected.
- GET bundle writes nothing.
- Snapshot creation explicit/idempotent.
- Video auto-dispute üretmez.
- Human dispute blocks related release.
- Existing tracking semantics preserved.

---

## Program 4 — Milestone domain ve minimal multi-release ledger

### Faz 4A — Pure compiler

- rule → milestone,
- basis points,
- minor units,
- deterministic largest remainder,
- release_mode.

### Faz 4B — Pure evaluator

- all-or-nothing,
- proportional cumulative delivery,
- evidence requirements,
- review hold,
- no provider/DB.

### Faz 4C — Minimal Mock Ledger v2

```text
pool_amount_minor
released_amount_minor
remaining_amount_minor
status pool|partially_released|released|refunded
```

- multiple release operations,
- cumulative released amount,
- remaining amount validation.

### Faz 4D — Milestone persistence/state machine

```text
pending
evidence_pending
eligible
held
release_pending
partially_released
released
disputed
cancelled
```

### Faz 4E — Settlement integration

- due milestones,
- evaluator,
- release candidates,
- no duplicate instruction,
- aggregate transaction status.

### Program 4 kabul kriterleri

- 20/30/40/10 rules four milestones.
- Amount sum exact.
- Legacy partial delivery semantics represented.
- Cumulative partial releases drift yapmaz.
- Second milestone release mock ledger'da çalışır.
- Open dispute/review release'i bloklar.
- Duplicate evaluation duplicate instruction üretmez.
- Fully completed transaction settled olur.
- Pure evaluator unit-testable kalır.

---

## Program 5 — Full payment lifecycle ve operational hardening

### Faz 5A — Release instructions

- deterministic idempotency key,
- instruction status,
- provider reference.

### Faz 5B — Payment attempts

- attempt number,
- request fingerprint,
- response,
- error.

### Faz 5C — Retry/failure review

- timeout/failure,
- payment review case,
- retry same instruction.

### Faz 5D — Reconciliation

- local/provider drift,
- reconcile service,
- manual/admin action.

### Faz 5E — Webhook contract

- signature verification interface,
- dedupe,
- async confirmation.

### Faz 5F — Refund/reversal

- policy,
- audit,
- provider adapter.

### Faz 5G — Processing jobs

- extraction/payment job records,
- attempts,
- last_error,
- recovery/retry.

### Program 5 kabul kriterleri

- Same idempotency key one instruction.
- Retry creates new attempt, not instruction.
- Provider failure state kaybetmez.
- Confirmation milestone released yapar.
- Reconciliation drift bulur.
- Refund/reversal audit edilir.
- Background task crash recoverable olur.

---

## Program 6 — Frontend vertical slices

Backend contract'ları frozen oldukça ilerler.

### Slice 1

- login/register,
- entity profile,
- acting entity selector.

### Slice 2

- transaction upload,
- invitation send,
- invitation accept.

### Slice 3

- party reconciliation,
- rule revision,
- validator/review findings.

### Slice 4

- tracking policy,
- package review,
- ratification.

### Slice 5

- milestone timeline,
- evidence upload,
- review/dispute.

### Slice 6

- audit/evidence bundle,
- payment status.

### Frontend kuralları

- Vite `/api` proxy.
- `credentials=include`.
- Query token kalıcı auth olarak kullanılmaz.
- Source quote yalnız authorized view.
- Error envelope merkezi işlenir.

---

## Program 7 — Privacy, provenance ve production readiness

- encrypted document storage,
- retention/deletion,
- page/section/bbox provenance,
- OCR version/confidence,
- RAG collection/chunk version,
- rate limiting,
- login throttling,
- password reset,
- email verification,
- backup/restore,
- structured logs,
- dependency/security scans,
- PostgreSQL migration readiness,
- production key management.

---

# 10. Berke–Yusuf paralel geliştirme planı

## 10.1 Rol sahipliği

### Berke — Platform ve integration lead

- migration,
- DB lifecycle,
- auth/session,
- legal entities,
- transaction ownership,
- state adapter,
- funding coordinator,
- settlement,
- payment ledger/lifecycle,
- integration branch,
- doc-sync.

### Yusuf — Deal lifecycle ve verification lead

- participants/invitations,
- audit service,
- party reconciliation,
- review,
- ratification API,
- evidence/dispute,
- pure milestone evaluator,
- domain/API tests,
- uygun wave'lerde frontend consumer.

## 10.2 Hot-file sahipliği

| Alan | Sahip |
|---|---|
| DB runner/connection/migrations | Berke |
| `transactions.py` cutover/refactor | Berke |
| `approvals.py` → ratification cutover | Yusuf |
| `settlement.py` | Berke |
| existing `decision.py` semantics | Berke review |
| new milestone evaluator | Yusuf |
| payment provider/ledger | Berke |
| participant/invitation services | Yusuf |
| `main.py` integration | Berke |
| requirements manifests | Berke |
| ARCHITECTURE/AGENTS doc-sync | Berke integration checkpoint |
| Child plan domain tests | workstream sahibi |

## 10.3 Integration branch

```text
program/domain-evolution-v2
```

Her wave branch'i son integration HEAD'den açılır.

## 10.4 Migration reservation

```text
001_baseline_current_schema          Berke
002_foundation_request_audit         Berke
003_identity_sessions                Berke
004_legal_entities_memberships       Berke
005_participants_invitations         Yusuf
006_audit_events                     Yusuf
007_transaction_lifecycle_v2         Berke
008_documents_extraction_runs        Berke
009_rule_set_versions                Berke
010_review_cases                     Yusuf
011_tracking_policy_versions         Berke
012_ratification_packages            Yusuf
013_evidence_records                 Yusuf
014_disputes                         Yusuf
015_milestones                       Berke
016_mock_ledger_v2                   Berke
017_release_instructions             Berke
018_processing_jobs                  Berke
```

Numaralar wave öncesi reserve edilir, yeniden numaralanmaz.

---

# 11. Wave bazlı paralel çalışma

## Wave H0

### Berke

- delivery capability guard,
- list demo flag,
- busy_timeout,
- stale docs.

### Yusuf

- unauthorized release regression tests,
- token leak tests,
- demo flag tests.

### Gate

- full suite green,
- security hole closed.

---

## Wave 0 — Foundation

### Berke Track A

```text
feat/foundation-db-migrations
```

- migration runner,
- stamping,
- connection lifecycle,
- state adapter,
- repository seams.

### Yusuf Track B

```text
feat/foundation-api-ci-contracts
```

- error envelope,
- response models,
- request ID tests,
- CI,
- auth matrix document,
- test helper cleanup.

### Freeze before merge

- ActorContext,
- error envelope,
- DB dependency,
- migration contract.

---

## Wave 1 — Identity and onboarding

### Berke Track A

```text
feat/identity-session-entities
```

Own files:

```text
schemas/identity.py
services/auth.py
services/identity.py
repositories/users.py
repositories/entities.py
routers/auth.py
routers/entities.py
migrations/003*
migrations/004*
```

### Yusuf Track B

```text
feat/participants-invitations-audit
```

Own files:

```text
schemas/participants.py
services/participants.py
services/invitations.py
services/audit.py
repositories/participants.py
repositories/invitations.py
routers/participants.py
routers/invitations.py
migrations/005*
migrations/006*
```

### Required interface freeze

`ParticipantService` §8.1.

### Integration gate

```text
register creator
→ create entity
→ authenticated upload
→ attach creator participant
→ invite counterparty
→ counterparty register
→ accept
→ confirm profile
```

---

## Wave 2 — Rule versions and review

### Berke Track A

```text
feat/document-rule-versioning
```

- document storage,
- hashes,
- extraction runs,
- rule versions,
- pipeline integration.

### Yusuf Track B

```text
feat/review-party-reconciliation
```

- review cases,
- reconciliation,
- review API,
- revision request contract.

### Required interface freeze

- RuleVersionService,
- ReviewService.

### Gate

```text
NEEDS_REVIEW
→ open case
→ revision
→ validate
→ PASS
```

---

## Wave 3 — Package and ratification cutover

### Berke Track A

```text
feat/ratification-package-canonicalization
```

- canonical serializer,
- stored bytes/string hash,
- package service,
- policy snapshot/version,
- FundingCoordinator implementation.

### Yusuf Track B

```text
feat/account-ratification-api
```

- package projection,
- ratification router,
- authorization,
- idempotency,
- superseded rejection.

### Required interface freeze

- RatificationPackageService,
- FundingCoordinator.

### Hot-file rule

`approvals.py` yalnız Yusuf tarafından değiştirilir. Provider çağrısı doğrudan yapılmaz; FundingCoordinator çağrılır.

### Gate

```text
PASS rules
→ confirmed parties
→ locked policy
→ package open
→ buyer ratifies
→ seller ratifies
→ funding exactly once
```

Account fixture regression cutover burada yapılır.

---

## Wave 4 — Evidence and dispute

### Berke Track A

```text
feat/evidence-authorized-ingestion
```

veya iş yüküne göre Yusuf ile ters.

- evidence repository,
- auth submit,
- file/payload hash,
- legacy decision adapter.

### Yusuf Track B

```text
feat/dispute-review-lifecycle
```

- dispute,
- actions,
- human-only open,
- evidence links.

### Gate

```text
video anomaly
→ review hold
→ human dispute
→ linked evidence
→ no release
```

---

## Wave 5 — Milestone and ledger prerequisite

### Berke Track A

```text
feat/milestone-persistence-ledger-v2
```

- milestone tables,
- compiler persistence,
- minimal multi-release ledger,
- aggregate transaction status.

### Yusuf Track B

```text
feat/pure-milestone-evaluator
```

- all-or-nothing,
- proportional cumulative,
- review/dispute hold,
- table tests.

### Required interface freeze

- MilestoneDraft,
- MilestoneEvidenceSet,
- MilestoneDecision,
- ReleaseCandidate.

### Integration ownership

`settlement.py` yalnız Berke tarafından değiştirilir.

### Gate

- two milestones release sequentially,
- no provider single-shot failure,
- partial delivery cumulative math correct.

---

## Wave 6 — Payment lifecycle and frontend consumer

### Berke Track A

```text
feat/release-instructions-payment-attempts
```

- instructions,
- attempts,
- retry,
- reconcile,
- processing jobs.

### Yusuf Track B option A

```text
feat/provider-failure-review-contract
```

veya option B:

```text
feat/account-deal-lifecycle-ui
```

- frozen API mock/fixtures ile frontend.

### Gate

- duplicate submission safe,
- provider failure recoverable,
- UI vertical slice account flow.

---

# 12. Aynı anda yapılmaması gereken işler

1. İki kişi `transactions.py` değiştirmez.
2. İki kişi migration runner dosyalarını değiştirmez.
3. Approval cutover ile package contract aynı branch'te rastgele geliştirilmez.
4. Milestone evaluator `settlement.py` içinde yazılmaz.
5. Ledger v2 gelmeden multi-milestone settlement kabul edilmez.
6. Legacy capability removal Wave 3 account E2E'den önce yapılmaz.
7. ARCHITECTURE/AGENTS iki branch'te eşzamanlı güncellenmez.
8. ExtractionJSON hiçbir child plan tarafından genişletilmez.
9. Review bypass geçici çözüm olarak approval path'e eklenmez.
10. GET evidence endpoint side-effect taşımaya devam ettirilmez.

---

# 13. Branch ve PR protokolü

## Branch süresi

- 1–3 gün.
- Her branch tek work package.
- Yeni wave branch'i integration branch'ten açılır.

## PR checklist

```text
[ ] Child plan maddesi
[ ] Domain contract etkisi
[ ] Migration etkisi
[ ] Security/privacy etkisi
[ ] Authorization matrix
[ ] Targeted tests
[ ] Full suite
[ ] Legacy compatibility
[ ] ExtractionJSON unchanged
[ ] decision.py pure
[ ] settlement single guard
[ ] Event/audit token/PII leak check
[ ] Doc-sync ihtiyacı
```

## Integration checkpoint

- branch merge,
- cross-feature E2E,
- migration smoke,
- full suite,
- doc-sync,
- master plan progress update.

---

# 14. API hedefi

## Auth

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
POST /api/auth/sessions/revoke
```

## Entities

```text
POST  /api/entities
GET   /api/entities
GET   /api/entities/{id}
PATCH /api/entities/{id}
```

## Transactions

```text
POST /api/transactions
GET  /api/transactions
GET  /api/transactions/{id}
```

Create:

```text
file
acting_entity_id
own_role
counterparty_email optional
```

## Invitations

```text
POST /api/transactions/{id}/invitations
GET  /api/invitations/{token}/preview
POST /api/invitations/{token}/accept
POST /api/transactions/{id}/invitations/{invite_id}/revoke
```

## Participants

```text
GET  /api/transactions/{id}/participants
PUT  /api/transactions/{id}/participants/me/profile
POST /api/transactions/{id}/participants/me/confirm
```

## Rules

```text
GET  /api/transactions/{id}/rule-sets/current
GET  /api/transactions/{id}/rule-sets
POST /api/transactions/{id}/rule-sets/{version}/revisions
POST /api/transactions/{id}/rule-sets/{version}/validate
```

## Tracking

```text
PUT  /api/transactions/{id}/tracking-policy
POST /api/transactions/{id}/tracking-policy/lock
```

## Ratification

```text
POST /api/transactions/{id}/ratification-packages
GET  /api/transactions/{id}/ratification-packages/current
POST /api/transactions/{id}/ratifications
```

## Reviews

```text
GET  /api/transactions/{id}/reviews
POST /api/transactions/{id}/reviews/{review_id}/actions
```

## Evidence

```text
POST /api/transactions/{id}/evidence/e-irsaliye
POST /api/transactions/{id}/evidence/video
GET  /api/transactions/{id}/evidence-records
GET  /api/transactions/{id}/evidence-bundle
POST /api/transactions/{id}/evidence-snapshots
```

## Disputes

```text
POST /api/transactions/{id}/disputes
GET  /api/transactions/{id}/disputes
POST /api/disputes/{id}/actions
```

## Milestones

```text
GET /api/transactions/{id}/milestones
GET /api/milestones/{id}
```

## Payment operations

```text
GET  /api/transactions/{id}/release-instructions
POST /api/release-instructions/{id}/retry
POST /api/transactions/{id}/payments/reconcile
```

---

# 15. Migration ve compatibility stratejisi

## 15.1 Additive first

- Eski tablolar ilk aşamada silinmez.
- Yeni tablolar eklenir.
- Legacy adapter mevcut transaction'ları taşır.

## 15.2 Baseline stamping algoritması

Pseudo:

```python
if schema_migrations_exists():
    apply_pending()
elif database_is_empty():
    create_schema_migrations()
    apply_all_from_001()
elif matches_legacy_baseline_fingerprint():
    create_schema_migrations()
    stamp_applied("001_baseline_current_schema")
    apply_from_002()
else:
    raise UnknownLegacySchemaError
```

## 15.3 Lifecycle classification

```text
legacy_v1
account_v2
```

## 15.4 Legacy removal gate

Şunlar account mode'da yeşil olmadan kaldırılmaz:

- create,
- invite,
- accept,
- participant confirm,
- rule review,
- policy lock,
- package,
- dual ratification,
- funding,
- evidence,
- settlement.

---

# 16. Test stratejisi

## 16.1 Test sınıfları

```text
unit
domain
repository
api
migration
security
e2e
legacy_compat
```

## 16.2 Scenario regression migration

Wave 0–2:

- legacy fixtures yeşil kalabilir.

Wave 3:

- approval-only,
- document-only,
- optional video,
- video anomaly,
- partial delivery

scenario testleri account-based fixture'a taşınır.

## 16.3 Migration tests

- empty DB,
- legacy DB,
- already migrated DB,
- unknown schema,
- interrupted migration,
- repeated run.

## 16.4 SQLite tests

- busy timeout,
- concurrent invitation accept,
- concurrent ratification,
- duplicate release instruction,
- last_seen throttle.

## 16.5 Auth tests

- duplicate email,
- invalid credentials,
- revoked/expired session,
- CSRF/Origin,
- cookie flags,
- disabled user.

## 16.6 Entity tests

- ciphertext != plaintext,
- HMAC equality,
- masked projection,
- unauthorized edit,
- same entity both sides rejected.

## 16.7 Invitation tests

- wrong email,
- expired,
- revoked,
- reused,
- creator conflict,
- exactly-once participant assignment.

## 16.8 Rule/package hash tests

- same stored canonical string same hash,
- key ordering stable,
- rule change changes hash,
- participant change changes hash,
- policy change changes hash,
- release_mode change changes hash.

## 16.9 Review tests

- NEEDS_REVIEW open case,
- revision,
- revalidate,
- resolution actor,
- blocking case prevents package.

## 16.10 Evidence tests

- unauthorized submit,
- wrong participant,
- duplicate external ref,
- file hash,
- event only evidence ID,
- GET no DB write,
- snapshot idempotent.

## 16.11 Milestone tests

- exact totals,
- largest remainder,
- cumulative partial release,
- all-or-nothing,
- second milestone release,
- open dispute hold,
- duplicate evaluation.

## 16.12 Payment tests

- idempotency,
- multiple release,
- failure,
- retry,
- reconciliation,
- refund/reversal.

---

# 17. Security ve privacy

## Password

- Argon2id,
- no plaintext,
- generic login error.

## Session

- high entropy,
- hash in DB,
- HttpOnly,
- Secure production,
- SameSite,
- CSRF/Origin,
- revoke/expiry.

## Invitation

- hash,
- expiry,
- single-use,
- email binding,
- revoke/reissue.

## Tax ID

- ciphertext,
- keyed HMAC lookup,
- last4,
- no log/event/public response.

## Raw documents

- local demo accepted risk,
- access restricted,
- production encryption future gate.

## Audit

- metadata allowlist,
- no raw request dump,
- request ID,
- actor/entity.

## IDOR

Her resource için unrelated user testleri.

---

# 18. Risk kaydı

| Risk | Mitigasyon |
|---|---|
| Scope explosion | child plans + wave gates |
| Merge conflict | hot-file ownership |
| Migration data loss | fingerprint + stamping + fail closed |
| SQLite locks | busy_timeout + short transactions + throttled writes |
| Dual auth drift | Wave 3 hard cutover |
| Regression ambiguity | scenario semantics definition |
| Partial delivery mismatch | explicit release_mode |
| Multi-release provider failure | ledger v2 prerequisite |
| Hash nondeterminism | stored canonical bytes |
| PII spread | projection allowlist + accepted-risk record |
| Review dead end | Program 2 recoverable review |
| Evidence GET writes | GET/POST separation |
| Cookie cross-origin failure | Vite proxy + same-origin production |
| Unilateral dispute resolution | access matrix + reviewer policy |
| Background task loss | processing_jobs |
| Frontend rewrite | frozen API vertical slices |

---

# 19. Hackathon ve post-hackathon ayrımı

Bu master program haftalar ölçeğindedir.

## Demo öncesi

Yalnız:

- H0 security hotfix,
- busy_timeout,
- doc/test count sync,
- gerekirse minimal CI.

## Demo sonrası

- Program 0 ve devamı.

Çalışan 214 testlik demo çekirdeği, yarışma öncesinde büyük refactor'a sokulmamalıdır.

---

# 20. Program genel kabul senaryosu

1. Berke register/login olur.
2. ABC A.Ş. entity'sini oluşturur/seçer.
3. Authenticated transaction oluşturur.
4. Sözleşme bytes hashlenir ve storage'a alınır.
5. Extraction run oluşur.
6. Validator review üretirse case açılır.
7. Rule revision yeni immutable version oluşturur.
8. Yusuf invitation ile katılır.
9. XYZ Ltd. entity'sini bağlar.
10. Party mismatch varsa review çözülür.
11. Tracking policy lock edilir.
12. Canonical package stored string üzerinden hashlenir.
13. Berke ABC adına ratify eder.
14. Yusuf XYZ adına aynı package'ı ratify eder.
15. Funding exactly once olur.
16. Milestones compile edilir.
17. E-irsaliye/video authorized actor tarafından sunulur.
18. Evidence hash ve actor taşır.
19. Video anomaly review hold üretir.
20. İnsan dispute açabilir.
21. Milestone evaluator release candidate üretir.
22. Ledger v2 multi-release destekler.
23. Release instruction idempotent oluşturulur.
24. Provider confirmation milestone'u released yapar.
25. Tüm milestones tamamlanınca transaction settled olur.
26. Bundle audit, package, evidence, milestones ve payment timeline içerir.
27. Password/session/invitation token/TCKN/VKN bundle'da bulunmaz.

---

# 21. Child plan dosyaları

```text
plans/done/00_delivery_authorization_hotfix.md
plans/ready/01_foundation_migration_db_api_ci.md
plans/ready/02_identity_legal_entity_party_onboarding.md
plans/ready/03_rule_versioning_ratification_manual_review.md
plans/ready/04_evidence_dispute_lifecycle.md
plans/ready/05_milestone_and_mock_ledger_v2.md
plans/ready/06_payment_lifecycle_operational_hardening.md
plans/ready/07_frontend_vertical_slices.md
plans/ready/08_privacy_provenance_production_readiness.md
```

Master plan tek `/plan-uygula` görevi değildir.

---

# 22. İlk uygulama sırası

```text
1. 00_delivery_authorization_hotfix
2. demo freeze / hackathon
3. 01_foundation_migration_db_api_ci
4. 02_identity_legal_entity_party_onboarding
5. 03_rule_versioning_ratification_manual_review
6. 04_evidence_dispute_lifecycle
7. 05_milestone_and_mock_ledger_v2
8. 06_payment_lifecycle_operational_hardening
9. 07_frontend_vertical_slices
10. 08_privacy_provenance_production_readiness
```

---

# 23. Implementer bağlayıcı notları

- Bu dosya tek seferde uygulanmaz.
- H0 programdan bağımsız önceliklidir.
- Her child plan baseline test ile başlar.
- Her wave targeted + full suite ile biter.
- Migration additive, fingerprinted ve testli olmalıdır.
- ExtractionJSON değişmez.
- `decision.py` saf kalır.
- `settlement.py` tek release guard sahibi kalır.
- Funding provider çağrısı approval/ratification router'a dağılmaz.
- Milestone multi-release, ledger v2 olmadan entegre edilmez.
- GET endpoint'ler side-effect üretmez.
- Token/PII event ve audit metadata'ya yazılmaz.
- Legacy state destructive rewrite edilmez.
- Scenario semantics regression olarak korunur.
- Doc-sync olmadan phase tamamlanmış sayılmaz.
