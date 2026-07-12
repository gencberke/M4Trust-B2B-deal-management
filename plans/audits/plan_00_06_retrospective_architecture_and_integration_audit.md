# Plan 00–06 Retrospective Architecture and Integration Audit

> **Auditor:** independent architecture/integration/reliability review (read-only)
> **Date:** 2026-07-12
> **Repository:** `M4Trust-B2B-deal-management` (github.com/gencberke/M4Trust-B2B-deal-management)
> **Audited branch:** `program/domain-evolution-v2` @ `673a4d0` (== `origin/program/domain-evolution-v2`)
> **Note:** repository documentation is in Turkish; this report quotes Turkish sources verbatim where relevant.

---

## 1. Executive Summary

Plans 00–06 genuinely transformed a two-day anonymous capability-link prototype into a coherent, layered B2B conditional-payment platform: versioned migrations, session/CSRF identity with encrypted tax identifiers, participant/invitation onboarding, immutable document/extraction/rule-set provenance, canonical hash-bound bilateral ratification, first-class evidence records, a human-controlled dispute lifecycle, and a contract-faithful Moka funding-unit payment model with idempotent funding and release coordinators. The full test suite passes (896 passed, 1 skipped, verified by execution), financial invariants are enforced by DB constraints and negative tests, and no secret/PII leakage was found in logs, events, audit metadata, or public responses.

However, **Plan 06 was never closed**. Its four waves (6A–6D) are merged into the integration branch and are well-tested at the service layer, but the plan's own closing obligations were not executed: the account settlement/release path is **not reachable from any runtime endpoint**, the `LEGACY_CAPABILITY_ACCESS_ENABLED` default was never flipped to `false`, the full scenario-fixture migration never happened, the plan file still sits in `plans/ready/` marked `Ready`, doc-sync was not performed (ARCHITECTURE.md/AGENTS.md are unaware of Plan 06), and the program→master closing merge is missing. In addition, one cross-plan seam defect was found: a high-confidence damage-signal video is quarantined at ingestion (`review_required`) but the settlement path reads only `verified` evidence and nothing ever opens a review case or verifies the record — the "matched damage ⇒ hold + manual review" invariant is structurally unreachable in the account path.

**Verdict: `SUCCESSFUL_WITH_TARGETED_REMEDIATION`.** No CRITICAL defects. Two HIGH findings, both rooted in the same cause (Plan 06 closure never executed), plus one HIGH-rated cross-plan seam defect that the missing closure currently masks. One focused interim plan is recommended before Plan 07.

---

## 2. Audit Scope and Method

- **Scope:** repository state from immediately before Plan 00 implementation through the current head of `program/domain-evolution-v2`. Plan 07 implementation is out of scope; work explicitly assigned to Plans 07/08/09 is not counted as a defect.
- **Method:**
  - Git archaeology over all 129 commits and 60+ branches to fix the two comparison points.
  - Full read of the authoritative plan corpus: `plans/done/00_*.md` … `05_*.md`, `plans/ready/06_*.md` (and `07_*.md` for deferral boundaries), `plans/planning/program_haritasi_paralel_calisma.md`, `AGENTS.md`, `ARCHITECTURE.md`.
  - First-hand code audit of the money paths: `services/payments/funding_coordinator.py`, `services/payments/release_coordinator.py`, `services/settlement.py`, `services/milestone_decision.py` (via callers), `db/migrate.py`, `db/migrations/*`, `config.py`, `main.py`, `routers/approvals.py`, `routers/evidence_submit.py`, `services/evidence_records.py`.
  - Four delegated read-only exploration sweeps: (a) runtime wiring inventory (routers/migrations/services/repositories vs. registration), (b) security/privacy leak sweep (logs, events, audit metadata, responses, Moka client/mock, cookies/CSRF, error handlers), (c) test-suite and CI inventory, (d) baseline snapshot reconstruction (commit `3ec9e8c` extracted to a scratch directory and analyzed in isolation).
  - Full test-suite execution (exact command and results in §10).
- **Read-only constraint respected:** no source, plan, or history was modified; the only artifact produced is this report.

---

## 3. Historical Baseline

```text
historical_baseline_sha      3ec9e8c
historical_baseline_message  "plan revizyonu: koordinasyon review düzeltmeleri ve paralellik çalışmaları" (2026-07-10)
reason_this_is_the_correct_baseline
  - The first Plan 00 implementation commit is 8604373 "fix: authorize delivery evidence endpoints"
    (branch hotfix/h0-delivery-authorization, merged via PR #6/#7).
  - 3ec9e8c is its direct parent lineage head (verified: `git merge-base --is-ancestor 3ec9e8c 8604373`;
    `git log 3ec9e8c..8604373` contains only the Plan 00 commit itself).
  - 3ec9e8c and 7836997 ("plan haritası") are planning-only commits: they created the program map and
    child plans 00–09 without touching runtime code. Runtime code at 3ec9e8c is identical to
    8be46d1 ("fix 2"), the last pre-program runtime change.
```

**Alternatives considered:** `8be46d1` (last runtime-affecting commit before planning) and `7836997` (first planning commit). `3ec9e8c` was chosen because the audit compares the *system* before the program began affecting runtime code, and including the committed plans in the baseline is harmless (they are the audit's own reference material). All three candidates share an identical `code/` tree.

**Baseline system (verified against the extracted snapshot of `3ec9e8c`):** single FastAPI app + one SQLite file; `init_db()` `CREATE TABLE IF NOT EXISTS` with one hand-rolled `ALTER TABLE` (no migration framework) (`code/backend/app/db.py:15-102`); 7 tables; **no users, sessions, login, or legal entities of any kind**; authorization purely via plaintext capability tokens compared with `==` (`routers/transactions.py:98-113`); **delivery evidence endpoints had no authorization at all** (`routers/delivery.py:129-182` took no token — anyone with a transaction id could post `delivered_quantity` and drive a mock release; the pre-fix test suite posted to them tokenlessly); mock-only payment provider (`make_payment_provider` raised `NotImplementedError` for anything but `"mock"`); one pool payment per transaction with `capture_ratio` partial approval; extraction stored append-only in `extracted_rules` with "latest-by-rowid" reads duplicated across five routers; no document storage, no rule versioning, no ratification package, no review workflow, no dispute records, no evidence records, no audit table; ~201 test functions.

---

## 4. Current Endpoint

```text
current_sha       673a4d0
current_message   "Merge pull request #57 from gencberke/feat/moka-multi-release-e2e"
                  (branch program/domain-evolution-v2, in sync with origin)
plan_06_completion_evidence
  IMPLEMENTED (waves merged into integration branch):
    - 6A: 143a1f9 / PR #54 (milestone/funding persistence + real pool funding);
      migrations 015/016/017 present AND registered in the startup runner
      (db/migrate.py:37-39 — applied by run_migrations on app startup, main.py:42-48)
    - 6B: db07736 + f76750d / PR #55 (pure milestone evaluator, 25 table-driven tests)
    - 6C: 5f99bd2 / PR #56 (settlement dual-path cutover + ReleaseCoordinator)
    - 6D: b910405 / PR #57 (contract-faithful multi-release E2E vs. real mock-Moka HTTP,
      funding-decline reconciliation)
    - Full suite green: 896 passed, 1 skipped (executed during this audit)
  NOT COMPLETED (plan closure):
    - plans/ready/06_milestone_funding_units_settlement.md still says "Durum: Ready — 2026-07-10";
      never moved to plans/done/, no deviation record
    - Doc-sync absent: ARCHITECTURE.md §5 still states "015-017 … app startup registry'sine bu
      Plan 05 kapanışında alınmaz" (now false) and §3.3 still describes the funding cutover as
      future; AGENTS.md's last entry is the Plan 05 close — no Plan 06 entry
    - 6D acceptance "legacy default off + tam fixture göçü tamam" not done:
      config.py:68 legacy_capability_access_enabled defaults to True; no `legacy_compat`
      marker exists anywhere in code/ (grep: zero matches); legacy scenario tests still run in
      legacy form
    - Branch protocol closure merge missing: origin/master is at 1a7ca4a (PR #53, Plan 05 close);
      the 9 Plan 06 commits exist only on program/domain-evolution-v2
    - The account settlement path has no runtime trigger (Finding B-1, §11)
```

Per the audit brief's warning, HEAD was **not** assumed to represent a fully integrated Plan 06 — and indeed it does not. The correct characterization: **Plan 06 is implemented at wave level and unclosed at plan level.**

---

## 5. Before vs After Architecture Comparison

| Dimension | Before (3ec9e8c) | After (673a4d0) |
|---|---|---|
| Schema management | `CREATE TABLE IF NOT EXISTS` + one inline `ALTER TABLE`; no versioning | Atomic migration runner with fail-closed legacy fingerprint stamping (`db/migrate.py:97-129`, `UnknownLegacySchemaError`), 17 registered migrations (001, 003–017, 023), per-migration `BEGIN IMMEDIATE` transactions |
| Tables | 7 (`transactions`, `extracted_rules`, `approvals`, `events`, `mock_payments`, `evidence`, `tracking_policies`) | ~31: adds `users`, `sessions`, `legal_entities`, `memberships`, `transaction_participants`, `transaction_assignments`, `transaction_invitations`, `audit_events`, `contract_documents`, `extraction_runs`, `rule_set_versions`, `review_cases`, `review_actions`, `ratification_packages`, `ratifications`, `evidence_records`, `disputes`, `dispute_actions`, `milestones`, `funding_units`, `provider_payments`, `provider_operations`, `fake_provider_payments`, `release_instructions`, `schema_migrations` |
| Identity & authz | None. Plaintext capability tokens only; delivery endpoints fully anonymous | Argon2id auth, hashed session tokens, HttpOnly+SameSite cookies, CSRF double-submit + Origin check, AES-256-GCM tax IDs + HMAC lookup (fail-closed without keys), membership/assignment scoping, prioritized `get_current_actor`; legacy tokens survive only as a flag-gated `legacy_v1` path |
| Transaction lifecycle | Single string-state flow, no CAS | Dual lifecycle: `legacy_v1` bit-identical + `account_v2` state machine with compare-and-set transitions (`services/account_lifecycle.py`) and canonical projection for legacy (`services/transaction_state.py`) |
| Document/extraction provenance | Markdown in `transactions` row; latest-by-rowid reads ×5 | `contract_documents` (SHA-256, storage_ref via `DocumentStorageProvider`), immutable `extraction_runs`, immutable `rule_set_versions` with content hash + DB immutability triggers; central `repositories/rule_sets.py::get_current` reader with legacy fallback |
| Review/reconciliation | `awaiting_review` was a dead-end state | `review_cases`/`review_actions` (append-only), validator NEEDS_REVIEW → blocking case, extracted↔declared↔confirmed party reconciliation, recoverable resolution back to `preparation` (4F-2), human-only `escalate_dispute` |
| Ratification | Two token clicks in `approvals` table | Canonical UTF-8 package (sorted keys, minor-unit ints), `package_hash` over stored bytes, DB triggers freezing bound inputs, supersede-on-input-change, `UNIQUE(package_id, participant_id)`, same hash shown to both sides, account approvals rejected on legacy endpoint (`approvals.py:79-88`) |
| Evidence | Event payloads only; bundle GET wrote to DB | First-class `evidence_records` (actor/entity/hash-bound, idempotent by `external_reference`/`file_sha256`, immutability triggers), active-state-only guard, deterministic video storage + orphan cleanup, side-effect-free bundle GET + explicit snapshot POST |
| Disputes | Nonexistent (a doc-string mention) | Human-only open (approvers), append-only actions, authorization matrix (comment/attach = both approvers, cancel = opener, resolve = opener or platform reviewer/admin), open dispute blocks release in the single guard |
| Payments | One mock pool payment per transaction, `capture_ratio` partial approve | Funding-unit model: milestone → N funding units, `OtherTrxCode = M4T-{tx8}-P{ver}-U{seq}`, one unit = one pool payment = whole approve (no capture_ratio in the port), fixed tranches for partial delivery, `UNIQUE(provider_profile, other_trx_code)` / `UNIQUE(package,sequence)` / 1:1 `provider_payments`, `provider_operations` with `UNIQUE(idempotency_key, attempt_no)` (016_funding_units_provider_payments.py:33-83) |
| Moka integration | None (mock shapes only) | Frozen contract DTOs + error catalog (fail-closed unknown codes), CheckKey SHA-256, Decimal serialization, sync httpx client with timeout→UNKNOWN (no blind retry), redacted traces, standalone contract-faithful mock server with independent redaction, client↔mock E2E incl. timeout-reconcile |
| Idempotency/concurrency | `other_trx_code` dedupe only | DB uniques throughout; funding replay produces no second payment (test-verified); release instruction unique per (unit, operation); CAS state transitions; race-safe evidence insert (IntegrityError → idempotent return, `evidence_records.py:216-231`); SQLite `BEGIN IMMEDIATE`, busy_timeout, request-scoped connections, background tasks own their connections |
| Error handling / observability | None | Standard error envelope, request-ID middleware on every response, sanitized 500s (no traceback leakage — verified) |
| Audit | None | `audit_events` in same connection/transaction as business mutation, allowlisted scalar-only metadata with forbidden-pattern rejection (token/password/card/PAN/TCKN/VKN/IBAN…) |
| Tests / CI | ~201 tests, no CI | 896 passing tests (75 test files), GitHub Actions on every push/PR: Python 3.12, `requirements-ci.txt`, full `pytest -q` |

The "expected pre-program weaknesses" list in the audit brief was verified item-by-item against the snapshot; every item held (capability-token access, no identity, no provenance, no rule versions, no canonical ratification, incomplete Moka, single mock pool payment, thin lifecycle safeguards).

---

## 6. Plan 00–06 Scorecard

| Plan | Score (0–5) | Summary |
|---|---|---|
| 00 — Delivery authorization hotfix | **5** | Real vulnerability (anonymous list + anonymous delivery evidence → anonymous release) confirmed present at baseline and closed. Guards run before channel/state checks; `DEMO_PUBLIC_DASHBOARD` default false; 15 regression tests in `test_delivery_authorization.py` incl. token-leak scan. |
| 01 — Moka contract mock + client | **5** | Frozen DTOs/errors, gateway port without `capture_ratio`, sync client (timeout→UNKNOWN, no blind retry), separate-process mock server with independent redaction, client↔mock E2E (now 9 tests), demo driver. Red lines respected: `mock_moka` never registered in the main app; main flow untouched. Documented deviations (TestClient bridge, optional detail amounts, "contract-faithful mock" labeling) are sound. |
| 02 — Foundation (migrations/DB/API/CI) | **5** | Fail-closed stamping runner exactly as specified (`migrate.py:101-114`), request-scoped `get_db` with commit/rollback/close, `BEGIN IMMEDIATE` helper, error envelope + request-ID registered in `main.py:38-40`, requirements manifests split, CI live. 12 migration-foundation tests. Nit: plan text mentions lint in `requirements-ci.txt`; no lint step exists (LOW). |
| 03 — Identity/entities/participants/invitations | **4** | Fully wired (routers in `main.py:60-63`), IDOR/scoping/CSRF/cookie tests present, tax-ID crypto fail-closed, invitation tokens hashed + single-pending-per-role + atomic CAS accept. Documented deviation (dual-mode create instead of global 401) is justified and recorded. Residual debt: `approvals.py` was never gated behind `LEGACY_CAPABILITY_ACCESS_ENABLED` (deferred "to Wave 3", which then never executed — see B-4); participant test fixtures use stub `users`/`memberships` tables instead of real 003/004 migrations (drift risk). |
| 04 — Provenance/rule versions/review/ratification | **5** | Every major requirement traced (see §7): immutable runs/versions with DB triggers, canonical package + golden hash tests, ratification API with same-hash-both-sides and superseded→409, recoverable review, two remediation rounds, real-app E2E close gate (765 tests at close). The two big deviations (no provider funding in 04; legacy cutover deferred) are committed coordination decisions (`program_haritasi` Revizyon #1/#2) — `SUPERSEDED_BY_COMMITTED_DECISION`, not defects. |
| 05 — Evidence records + dispute lifecycle | **4** | Closed with corrective migration 023; 013/014 registered; `evidence_submit`/`disputes` routers wired; active-state guard, hash-first video replay + orphan cleanup, dispute authorization matrix, human-only escalation — all present and tested. Debt: `verify_evidence` exists only as a service (no runtime caller), which combines with a 6C filter into seam defect B-3; evidence records carry `milestone_id=NULL` awaiting an 06-side fill that never came. |
| 06 — Milestones/funding units/settlement cutover | **3** | 6A/6B/6C/6D code is merged, internally strong (fail-closed schedule materialization with per-field drift checks, funding_coordinator.py:153-259; exactly-once funding event, :529-568; idempotent release instructions; PaymentAlreadyApproved reconcile-as-success, release_coordinator.py:177-205) and E2E-tested against real mock-Moka HTTP. But the plan's closure did not happen: no runtime trigger for account settlement (B-1), legacy default-off + fixture migration not done (B-2), plan lifecycle/doc-sync/master merge missing (B-2). "Mostly implemented but important gaps remain." |

---

## 7. Requirement-to-Code Traceability

Statuses use the audit's fixed vocabulary. Representative traceability (full underlying evidence in §18):

**Plan 00**
- Delivery guards (seller|manager, before channel guard) → `routers/delivery.py:124-131` + resolve helpers → tests `test_delivery_authorization.py` → **IMPLEMENTED_AND_INTEGRATED**
- List env gate → `config.py:63,105` + `routers/transactions.py` list handler → tests → **IMPLEMENTED_AND_INTEGRATED**
- SQLite busy_timeout → `db/connection.py:11-21` → **IMPLEMENTED_AND_INTEGRATED**

**Plan 01**
- Contract freeze (`contracts.py`/`errors.py`), port without capture_ratio (`ports.py`/`domain.py`), CheckKey (`moka/authentication.py`), Decimal serializer, client timeout→UNKNOWN (`moka/client.py`), redaction (`moka/redaction.py`), mock server (`backend/mock_moka/`), E2E chain + leakage tests (`test_moka_e2e_contract.py`) → **IMPLEMENTED_AND_INTEGRATED** (integration by design = side panel; correctly not registered in main app)
- Sandbox validation → explicitly out of scope, labeled → **SUPERSEDED_BY_COMMITTED_DECISION** (labeling decision)

**Plan 02**
- Runner + stamping + fail-closed → `db/migrate.py:97-129` → `test_db_foundation.py` (12) → **IMPLEMENTED_AND_INTEGRATED**
- `get_db` lifecycle → `db/connection.py:29-40`, used by all 13 routers → **IMPLEMENTED_AND_INTEGRATED**
- Error envelope + request-ID → `api/errors.py`, `middleware/request_id.py`, registered `main.py:38-40` → **IMPLEMENTED_AND_INTEGRATED**
- CI → `.github/workflows/backend-ci.yml` (full suite, no heavy deps) → **IMPLEMENTED_AND_INTEGRATED**
- `transaction_state` contract → `services/transaction_state.py` (18 tests) → **IMPLEMENTED_AND_INTEGRATED**

**Plan 03**
- 003–007 migrations; auth (Argon2id, hashed session tokens, CSRF+Origin: `services/auth.py:203-243`); entities w/ AESGCM+HMAC (`services/identity.py`, fail-closed `KeyConfigurationError`); `ParticipantService` frozen trio; invitations (hashed token, preview w/o PII, supersede-per-role, CAS accept); audit same-connection allowlist (`services/audit.py`); ownership cutover dual-mode create + assignment scoping + `canonical_state` → all wired in `main.py` → **IMPLEMENTED_AND_INTEGRATED**
- "Anonymous create returns 401" → deliberately narrowed to dual-mode (documented in plan status block + PR #28) → **IMPLEMENTED_DIFFERENTLY_WITH_JUSTIFICATION**
- Approvals legacy-flag gating → deferred in writing, still absent → **PARTIALLY_IMPLEMENTED** (carried debt, see B-4)

**Plan 04**
- 008–012 migrations incl. immutability triggers; `DocumentStorageProvider`; pipeline → `services/transaction_pipeline.py`; central `rule_sets.get_current` w/ legacy fallback; `ReviewService` frozen; reconciliation reason-codes; pure funding-plan compiler (largest-remainder, `PROVIDER_CAPABILITY_CONFLICT` rejection — 19 tests); canonical package (golden hash tests) + supersede; FundingCoordinator v1 (no provider); ratification API (same hash both sides, superseded→409, one user cannot ratify both sides); rule revisions (CAS stale-parent, auto re-validate, package supersede); 4F-2 recovery to `preparation` → **IMPLEMENTED_AND_INTEGRATED** across the board
- Funding exactly-once + legacy default-off → moved to 06 by Revizyon #1/#2 → **SUPERSEDED_BY_COMMITTED_DECISION** (for Plan 04)

**Plan 05**
- 013/014 + 023 corrective; `EvidenceService` frozen four functions; account evidence endpoints (state guard 409 `EVIDENCE_SUBMISSION_STATE_INVALID`, seller/manager-only, idempotent duplicates); settlement reads via `collect_transaction_delivery_evidence`; `has_open_dispute` incl. transaction-wide blocking (`repositories/disputes.py:65-81`); dispute API matrix; `escalate_dispute` human-only via 023-constrained action; 5C read-only bundle + explicit snapshot → **IMPLEMENTED_AND_INTEGRATED**
- `verify_evidence` → service exists, no runtime caller → **IMPLEMENTED_BUT_WEAKLY_INTEGRATED** (feeds defect B-3)

**Plan 06**
- 015/016/017 in startup registry → **IMPLEMENTED_AND_INTEGRATED**
- Schedule persistence + OtherTrxCode derivation + fail-closed drift checks (`funding_coordinator.py:95-259`) → **IMPLEMENTED_AND_INTEGRATED** (invoked at runtime through ratification: `services/ratifications.py:234 → ensure_pool_funded`)
- FundingCoordinator v2 (partial failure → `funding_pending` + `PAYMENT_POOL_CREATION_FAILED` blocking case; timeout → `pool_creation_unknown` + detail reconcile, no blind retry) → **IMPLEMENTED_AND_INTEGRATED**
- `make_payment_gateway` (fake=SQLite-backed store / moka_http) → **IMPLEMENTED_AND_INTEGRATED**
- Pure milestone evaluator (frozen types, tranche thresholds, video-advisory semantics, AST-enforced import boundary) → **IMPLEMENTED_AND_INTEGRATED** (as a library)
- Settlement cutover 6C: dual path, single guard incl. review+dispute, ReleaseCoordinator idempotent instructions, PaymentAlreadyApproved reconcile, approval_unknown, aggregate recompute, `settled` transition → code complete, **BUT** `evaluate_settlement` is invoked only from legacy routers (`approvals.py:143`, `delivery.py:156,199`), both unreachable for `account_v2` → **IMPLEMENTED_BUT_WEAKLY_INTEGRATED** (B-1)
- 6D full-scenario cutover: multi-release E2E exists (2 strong tests) but drives the flow by direct service calls over a seeded DB; legacy default-off flip: **MISSING**; `legacy_compat` fixture set: **MISSING**; plan lifecycle/doc-sync/master merge: **MISSING** (B-2)

---

## 8. Cross-Plan Integration Analysis

The combined system holds together well below the last seam:

- **02→03→04 chain:** frozen `ActorContext`/`get_current_actor` signatures were honored — 3B coded against stubs and the real session actor slotted in without breaking contract tests. The central `rule_sets.get_current` seam successfully absorbed five duplicated latest-by-rowid readers, with a legacy fallback that keeps `legacy_v1` byte-stable.
- **04→05→06 chain:** the package binds document hash, rule version/hash, confirmed snapshots, locked-policy snapshot, and the 4C funding schedule; 6A materializes exactly that schedule with per-field drift verification (fail-closed), so a superseded or tampered package cannot fund. Account release readiness reads ratifications and the policy snapshot **from the package**, not from legacy `approvals` (`settlement.py:281-309`) — a clean cut.
- **Frozen-interface discipline worked:** `ensure_pool_funded` kept its Plan 04 signature while v2 filled in (with an explicit fallback to v1 behavior if 015–017 tables are absent, `funding_coordinator.py:76-80,586`; registry now includes them so the fallback is dormant).
- **Single-guard discipline held:** no router imports a payment gateway; only `settlement.py`/coordinators do (verified by import sweep). The legacy path still funnels through the same `evaluate_settlement` entry.
- **The one broken seam** is ingestion→settlement in the account path (B-3 below) plus the missing runtime trigger (B-1).

Dual-lifecycle coexistence is coherent: `legacy_v1` behavior is bit-preserved (its tests still pass unmodified), account rows never produce capability tokens, legacy endpoints 403/409 account rows, and the account path never reads legacy `approvals`/`mock_payments`.

---

## 9. End-to-End Flow Results

| Flow | Runtime-reachable? | Evidence |
|---|---|---|
| Register/login → entity → authenticated create → participants → invitation → accept → declared/confirmed profiles | **Yes** | Routers wired (`main.py:54-66`); `test_transaction_ownership_cutover.py` (20), `test_auth_router.py`, `test_invitations_router.py`, `test_participants_router.py`; IDOR/scoping tests |
| Upload → durable storage → extraction run → immutable rule version → validation → review when required | **Yes** | `transaction_pipeline.py` from `routers/transactions.py`; provenance immutability tests |
| Recoverable review (NEEDS_REVIEW / party mismatch → blocking case → revision → revalidate → resolve → back to preparation) | **Yes** | `rule_sets` + `reviews` routers; `test_review_resolution_e2e.py`; blocking case cannot be bypassed by `resolve_continue` (router matrix) |
| Ratification (readiness → canonical package → same hash both sides → buyer + seller ratify) | **Yes** | `ratifications` router → `services/ratifications.py`; same-hash and superseded→409 tests; one user for both sides → 403 |
| Funding (double ratification → schedule materialized → one pool payment per unit → active) | **Yes** | `services/ratifications.py:234` → `ensure_pool_funded` with default fake gateway (SQLite store); exactly-once verified by `test_ratification_package.py:281` |
| Evidence submission (seller/manager, active-only, idempotent) | **Yes** | `evidence_submit` router; 14 API tests |
| Dispute lifecycle (human-only open, action matrix, blocks release) | **Yes** (open/actions) | `disputes` router; 19 API tests |
| **Release / settlement / settled (account_v2)** | **No — service-only** | `evaluate_settlement` has no account-path runtime caller (B-1). Proven correct at service level: `test_settlement_funding_cutover.py` (6), `test_moka_multi_release_e2e.py` (2, real client↔mock-server HTTP) |
| Legacy demo flow (tokens, approvals, delivery, decision) | **Yes** | Preserved bit-identical; `test_api_flow.py`, `test_delivery_flow.py` still green |

**Invariant checks requested by the brief** — all verified, with one breach:

- LLM proposes / validator gates / humans ratify / deterministic code executes / LLM never moves money: **holds** (LLM output cannot become an active rule without PASS; release only via deterministic coordinators).
- Video alone cannot determine quantity/payment; anomalies never auto-create disputes; manager preference cannot weaken contractual evidence: **holds in code and tests** (`test_milestone_decision.py:242`, evaluator + `decision.py`), **but** see B-3: in the account path a high-confidence damage video is silently starved out of evaluation rather than producing hold+review.
- One funding unit = one Moka pool payment, approved as a whole; partial delivery via fixed tranches: **holds** (port has no capture_ratio; 016 uniques; tranche E2E).
- Package/ratification binding cannot go stale; superseded package cannot fund: **holds** (CAS + supersede + `get_current`+`complete`+integrity checks in both coordinators).
- Blocking review cannot be bypassed: **holds** (checked at funding, at evaluator, and again at the release guard).
- Funding and release idempotent; uncertain outcomes reconciled, not blindly retried: **holds** (replay tests; timeout→UNKNOWN→detail reconcile in both coordinators and in the E2E).
- Routers own no provider decisions; guards centralized: **holds**.

---

## 10. Test and CI Evidence

**Executed by the auditor:**

```text
cd code && ./.venv/Scripts/python.exe -m pytest -q
→ 896 passed, 1 skipped, 32 warnings in 31.60s   (venv Python 3.13.0, Windows)
```

The 1 skip is the OpenCV-codec-dependent frame-sampler test (self-skipping without the video profile, by design). Warnings are FastAPI `on_event` deprecations and a Starlette TestClient deprecation — no functional impact.

**CI** (`.github/workflows/backend-ci.yml`): every push and PR; Python 3.12; `pip install -r requirements-ci.txt` (core + pytest, no RAG/video); `pytest -q` over the full suite. No lint/type step, no coverage gate.

**Test-quality observations:**
- Money-path negatives are genuinely covered: double funding, double release, stale package, review/dispute bypass, provider timeout/unknown, partial decline + same-OtherTrxCode retry (§4 of the test inventory; e.g. `test_settlement_funding_cutover.py:229,247,269,293`, `test_moka_e2e_contract.py:251`).
- The suite consistently asserts *absence* of unsafe behavior (token/PII leakage scans, auth rejections, no auto-dispute). No test encodes unsafe behavior as expected.
- Weaknesses: (a) most router tests run against bespoke single-router `FastAPI()` apps with `get_db`/`get_current_actor` overridden — only the reviews router has a "real app registers these routes" smoke test, so a future `main.py` wiring omission would be caught for reviews only; (b) `participants_fixtures.py:56-73` builds stub `users`/`memberships` tables instead of applying migrations 003/004 (schema-drift risk, self-acknowledged in the fixture docstring); (c) funding/settlement fixtures seed `account_v2` state by direct multi-table INSERTs and drive the flow by direct service calls — they prove service-layer correctness, not product-surface reachability (which is exactly how B-1 stayed invisible to a green suite).

---

## 11. Breaking Bugs and Risks

### B-1 · HIGH — Account release/settlement is not reachable from the runtime product

```text
severity                HIGH
affected plan           06 (Faz 6C/6D closure)
affected code           services/settlement.py::evaluate_settlement (account branch);
                        callers: routers/approvals.py:143, routers/delivery.py:156,199 (legacy only);
                        routers/evidence_submit.py:14 ("settlement'a bağlanmaz — bu Berke'nin entegrasyon işi")
observed behavior       For account_v2 transactions no API call ever invokes evaluate_settlement:
                        approvals.py:79-88 rejects account rows (ACCOUNT_RATIFICATION_REQUIRED);
                        delivery.py requires capability tokens that account rows do not possess;
                        evidence_submit deliberately does not call settlement. verify_evidence
                        (services/evidence_records.py:262) also has no runtime caller.
reproduction/evidence   grep evaluate_settlement across code/backend/app → only the two legacy routers.
                        All Faz 6C/6D tests invoke settlement.evaluate_settlement() directly as a
                        Python function (test_settlement_funding_cutover.py:190-330,
                        test_moka_multi_release_e2e.py:143-165).
architectural impact    A funded account transaction (state=active) is a dead end in the running
                        product: evidence can be submitted but nothing evaluates milestones, releases
                        units, or reaches `settled`. The Plan 06 "cutover" exists as a library, not as
                        product behavior. Plan 07 (reconcile/retry endpoints, startup recovery) builds
                        directly on this path.
required correction     Wire the trigger: call evaluate_settlement for account_v2 after successful
                        evidence submission (mirroring legacy delivery.py) and after review/dispute
                        resolution; alternatively (or additionally) an explicit authorized
                        settlement-evaluation endpoint. Decide the runtime story for verify_evidence.
blocks Plan 07?         YES (also formally: program haritası §1 forbids starting 07 before 06 is done/)
```

### B-2 · HIGH — Plan 06 closure never executed (cutover, lifecycle, doc-sync, master merge)

```text
severity                HIGH (process + integration debt cluster, same root cause as B-1)
affected plan           06 (Faz 6D acceptance + repo protocol)
affected code/files     config.py:68,110-112 (legacy_capability_access_enabled default True — 6D
                        acceptance requires default False); no `legacy_compat` marker anywhere
                        (fixture migration not done); plans/ready/06_*.md still "Durum: Ready";
                        ARCHITECTURE.md §3.3/§5 stale (still claim 015-017 unregistered and funding
                        future); AGENTS.md ends at Plan 05; origin/master = 1a7ca4a (Plan 05 close),
                        Plan 06's 9 commits unmerged to master.
observed behavior       The repo's own lifecycle protocol (AGENTS.md: status block + move to done/ +
                        doc-sync; program haritası §2: program→master merge per completed plan) was
                        followed for Plans 00-05 and abandoned for 06.
architectural impact    The binding technical reference no longer describes the actual system; the
                        "demo-ready master" invariant now points at a pre-Plan-06 system; the legacy
                        capability surface (including unauthenticated-by-design token flows) remains
                        default-enabled contrary to the committed cutover decision.
required correction     Execute the closure: flip default (env-reopenable), migrate/mark legacy
                        fixtures, doc-sync ARCHITECTURE/AGENTS, move plan file to done/ with deviation
                        record, merge program→master once the gate is green.
blocks Plan 07?         YES (same sequencing rule; also 07's doc/plan base would be stale)
```

### B-3 · HIGH — Damaged-video evidence is quarantined and then ignored: "matched damage ⇒ hold + review" unreachable in the account path

```text
severity                HIGH (money-safety control disconnected; currently masked by B-1)
affected plans          05 (5A ingestion status) × 06 (6C verified-only read) — seam defect
affected code           routers/evidence_submit.py:229-232 (_video_verification_status →
                        "review_required" on high-confidence damage; no review case opened, no event
                        beyond evidence_submitted);
                        services/settlement.py:343-355 (_verified_evidence_rows filters
                        verification_status = 'verified' only);
                        services/evidence_records.py:262 (verify_evidence — no runtime caller);
                        services/settlement.py:461-489 (_open_account_video_review_if_needed can only
                        fire on findings derived from *verified* video rows).
observed behavior       A video with matched damage signals ≥ threshold is stored as review_required
                        and then never participates in milestone evaluation; no review case is opened
                        at ingestion; no endpoint can flip it to verified. If the verified e-irsaliye
                        shows sufficient quantity, units become eligible and release would proceed
                        despite the damage evidence — the opposite of the documented invariant
                        (ARCHITECTURE §3.4/§6.16; evaluator itself implements damage→hold correctly
                        but is starved of the signal).
reproduction/evidence   Static trace above; no test covers "review_required video then settlement" —
                        existing anomaly tests feed the evaluator directly or use verified rows.
architectural impact    Once B-1 is fixed (settlement trigger wired), this becomes a live release-
                        despite-evidence hole. Fixing B-1 without B-3 would be worse than fixing both.
required correction     Either open a blocking settlement review case at ingestion when the analyzer
                        yields review_required, or include review_required video rows in the advisory
                        summary (quarantine for quantity, not for anomaly signals), plus a regression
                        test: damaged video + full e-irsaliye ⇒ hold + review case, no release.
blocks Plan 07?         YES (must land together with B-1)
```

### B-4 · MEDIUM — `routers/approvals.py` not gated by `LEGACY_CAPABILITY_ACCESS_ENABLED`

Deferred in writing during Plan 03 ("Wave 3 ratification cutover'ında ele alınacak", AGENTS.md) — that window was Plan 04/06 and it never happened. With the flag set to `false`, party/manager views, delivery, and the legacy evidence GET are disabled (`transactions.py:563-569`, `delivery.py:124-131`, `evidence.py:129-131`) but token-based approval → pool payment → settlement on `legacy_v1` rows remains fully live (`approvals.py:69-156`). Not an account-path risk (account rows are rejected at :79), but the kill-switch is incomplete. Fix alongside B-2. **Blocks Plan 07: no** (but trivially bundled with the closure plan).

### B-5 · MEDIUM — `PAYMENT_PROVIDER=moka_http` crashes the legacy approval path

`services/payment_provider.py:182-187` (legacy factory) raises `NotImplementedError` for anything but `"mock"`, while the account factory supports `{"fake","mock","moka_http"}` (`funding_coordinator.py:438-453`). Setting `PAYMENT_PROVIDER=moka_http` (a value `config.py:49` documents) makes any legacy two-party approval 500. Guard the legacy path explicitly (mock-only with a clear error, or map moka_http→mock for legacy). **Blocks Plan 07: no.**

### B-6 · LOW — Latent/dormant items worth recording

- `Settings.from_env()` re-parsed per call sitewide; `access_control.py:45` opens a second ad-hoc connection per authenticated request (inconsistent DI; functionally safe single-worker).
- `_reconcile_unknown_unit` (`funding_coordinator.py:353`) marks a unit `approved` on detail=APPROVED without upserting a provider_payments row in that branch — unreachable today at create-time (mock cannot be approved before create returns) but a trap for Plan 07 reconciliation reuse.
- Heavy RAG objects re-instantiated per upload (performance only).
- Isolated-app test pattern: add "real app registers routes" smoke tests for the other account routers (only reviews has one).

---

## 12. Security and Privacy Findings

A dedicated sweep across logs, event payloads, audit metadata, public responses, the Moka client, the mock server, cookies/CSRF, and error handlers found **no leakage of any item on the audit's forbidden list** (capability/session/CSRF tokens, passwords/hashes, invitation tokens, CheckKey, CardToken, PAN/CVC/PIN/track data, TCKN/VKN, provider credentials, raw documents). Highlights:

- `services/audit.py` rejects non-allowlisted keys, forbidden key markers, and sensitive-shaped values before insert. Every `emit()` call site was inspected — none passes tokens/secrets; the evidence bundle applies a second independent scrubbing layer.
- Moka client and mock server implement **two independent** redaction layers (client `moka/redaction.py`; mock `mock_moka/app.py:104-151`); E2E tests scan traces and persisted rows for raw secrets.
- Invitation tokens hashed at rest; preview endpoint PII-free; no invitation list endpoint exists to leak anything.
- Unhandled exceptions return a fixed sanitized envelope (`api/errors.py:75-93`); no traceback leaves the process.

Findings (none blocking):
- **MEDIUM (pre-existing since baseline, not a Plan 00–06 regression):** legacy `buyer/seller/manager_token` stored plaintext and compared with non-constant-time `==` (`001_baseline_current_schema.py:12-13`; `transactions.py:91-102`). Contrast: invitation/session/CSRF tokens are hashed and CSRF uses `hmac.compare_digest`. Reasonable home: the legacy default-off cutover (interim plan) plus Plan 09 hardening.
- **MEDIUM:** `SESSION_COOKIE_SECURE` defaults to `false` (`config.py:66,108`) — documented opt-in; consider fail-closed default before any non-local deployment (Plan 09 territory).
- **LOW:** invited email address logged by `FakeNotificationProvider` (`notifications.py:58`); CheckKey redaction exposes 10 hex chars of a SHA-256 digest (cosmetic).

---

## 13. Legacy Compatibility Assessment

The additive-first strategy worked as designed. `legacy_v1` transactions run bit-identically: schema fingerprint stamping protects existing DBs (unknown schemas fail closed with zero mutation), the legacy decision/settlement/provider path is untouched (`settlement.py:177-246`), legacy tests pass unmodified, and account logic never falls back to legacy data (readiness reads ratifications/package snapshot, not `approvals`; funding coordinator rejects `legacy_v1` rows outright, `funding_coordinator.py:595-596`). The unfinished part is the *retirement* half: default-off flip, fixture migration, and the approvals kill-switch gap (B-2/B-4). Removal of legacy tables/paths is correctly deferred behind the post-09 removal gate.

---

## 14. Deferred Plan 07–09 Concerns (correctly NOT counted as defects)

`NOT_A_DEFECT_FUTURE_PLAN`: productized reconciliation service + reconcile/retry endpoints, authorized undo/refund, `018_processing_jobs` + startup crash recovery, redacted payment-trace endpoint, mock fault matrix (07); all account-flow frontend and any UI-driven triggers (08); versioned tracking-policy table (019), document-storage reference migration (020), auth verification/reset tokens (021), extraction-provenance extensions (022), NER-grade masking, production cookie/ops hardening (09). Migration numbering gaps (002 reserved; 018–022 reserved) are documented reservations — git history confirms those files never existed.

One boundary note: Plan 06's own text claims 6C/6D acceptance items ("%50 teslim demosu … yürür", "legacy default off … tamam") that are *not* deferred — those are counted above (B-1/B-2), while everything in this section is not.

---

## 15. Overall Verdict

```text
SUCCESSFUL_WITH_TARGETED_REMEDIATION
```

1. **Did Plans 00–06 materially transform the original prototype into the intended architecture?** Yes — every architectural pillar of the v2 program (identity, provenance, immutable versions, canonical ratification, first-class evidence, human-controlled disputes, funding-unit payments) exists, is migration-backed, and is test-protected.
2. **Were the plans implemented as designed or validly superseded?** Plans 00–05: yes, with documented, justified deviations recorded in the plans themselves and in the coordination map (Revizyon #1–5). Plan 06: waves implemented as designed; the closing acceptance items were not executed and were not superseded by any committed decision.
3. **Are the features genuinely integrated into one runtime?** Almost entirely yes — 13/13 routers registered, 17/17 migrations in the startup runner, zero dead services/repositories, funding reachable end-to-end through the real API. The single material exception is the account release/settlement trigger (B-1).
4. **Are the original working flows still protected?** Yes — legacy behavior is bit-preserved, flag-gated (with the B-4 gap), and its tests pass unmodified; fail-closed stamping protects existing databases.
5. **Is the current system internally coherent?** Yes at the design level; the incoherence is documentation vs. code (stale ARCHITECTURE/AGENTS re Plan 06) and one ingestion↔settlement seam (B-3).
6. **Are there breaking bugs that should block Plan 07?** Yes: B-1 (no runtime release path), B-3 (damage-video control disconnected), and the B-2 closure cluster. No CRITICAL (money-duplication/leakage) defects were found.
7. **Can Plan 07 safely begin now?** Not yet. Plan 07 hardens exactly the path that is not yet product-reachable, and the program's own sequencing rule requires 06 in `done/` first. After the single interim plan below, yes.

---

## 16. Interim Plan Recommendation (one plan)

**Plan title:** `06X — Plan 06 Kapanış Entegrasyonu: Account Release Runtime Cutover + Legacy Default-Off`

- **Why before Plan 07:** Plan 07 (reconcile/retry/jobs/trace) operates on the funding→release→settled path; that path must first exist in the running product, and the damage-video control must be connected before the release trigger goes live. The program map forbids starting 07 while 06 is not in `done/`.
- **Exact defects addressed:** B-1, B-2, B-3, B-4 (B-5 optional one-liner guard).
- **Scope:**
  1. Runtime settlement trigger for `account_v2`: invoke `evaluate_settlement` after successful account evidence submission (`routers/evidence_submit.py`, both endpoints) and after blocking review/dispute resolution; keep the caller-commits pattern.
  2. Damage-video seam: on `review_required` video ingestion open a blocking `phase=settlement`, `source_type=video` review case (idempotent), or feed anomaly signals from `review_required` rows into the advisory summary; add the regression test "damaged video + full e-irsaliye ⇒ hold + review, zero provider calls".
  3. Legacy cutover completion: `legacy_capability_access_enabled` default `false` (env-reopenable); gate `routers/approvals.py` behind the flag; move remaining legacy scenario tests to account fixtures or mark the narrow surviving set `legacy_compat` with the flag force-enabled.
  4. Closure mechanics: doc-sync ARCHITECTURE (§1/§3.3/§4.1/§5/§6 — funding-unit model, new tables/states, corrected 015-017 sentence, §6 duplicate numbering) and AGENTS (Plan 06 entry + test count); move `06_*.md` to `plans/done/` with status block and deviation record; merge `program/domain-evolution-v2` → `master` once green.
- **Explicitly out of scope:** everything in §14 (07/08/09 material); no new provider operations; no schema changes beyond none-expected (if the review-case route needs nothing new, zero migrations).
- **Likely owner:** Berke (integration lead — `main.py`/`config.py`/`settlement.py`/doc-sync are his hot files per the ownership map); Yusuf: evidence_submit trigger tests + fixture migration of his domains + the B-3 regression test.
- **Dependencies:** none beyond current HEAD.
- **Affected files/domains:** `routers/evidence_submit.py`, `routers/reviews.py`/`disputes.py` (post-resolution trigger), `services/settlement.py` (only if the advisory-inclusion variant is chosen), `config.py`, `routers/approvals.py`, tests, ARCHITECTURE.md, AGENTS.md, plan file move.
- **Migration implications:** none expected; if any, additive per protocol.
- **Required regression tests:** account E2E through the real app (TestClient, session+CSRF): ratify → funded → evidence → release (½ then full, two separate approves) → settled; damaged-video hold test (above); flag-off legacy surface test incl. approvals; replay-safety re-run.
- **Acceptance criteria:** Plan 06's own acceptance list finally green *through the product surface*; full suite green; master == program tip; docs synced.
- **Stop condition:** no scope creep into Plan 07 hardening (no retry endpoints, no jobs, no trace endpoint) — if a fix seems to need them, stop and re-plan.

*(No second interim plan is recommended; all blocking findings share the single root cause "Plan 06 closure not executed".)*

---

## 17. Exact Conditions for Starting Plan 07

1. `evaluate_settlement` reachable for `account_v2` through at least one authorized product path, proven by a real-app E2E test (not direct service invocation).
2. Damage-video ⇒ blocking review behavior connected and regression-tested (B-3 closed).
3. `LEGACY_CAPABILITY_ACCESS_ENABLED` default `false`, `approvals.py` gated, legacy tests migrated or `legacy_compat`-scoped.
4. Plan 06 file in `plans/done/` with status block; ARCHITECTURE/AGENTS synced; `master` fast-forwarded to the program tip.
5. Full suite green locally and in CI at that commit.

---

## 18. Evidence Appendix

**Comparison points**
- Baseline: `3ec9e8c` (parents chain `8be46d1` ← `3bb36da` ← `8e63c16` ← `8ca619e`); first program commit `8604373` (PR #6), test `bcc3c6a`, merge `bf43a80` (PR #7).
- Endpoint: `673a4d0` = `origin/program/domain-evolution-v2`; `origin/master` = `1a7ca4a`; `git rev-list --count origin/master..HEAD` = 9 (all Plan 06); `git rev-list --count HEAD..origin/master` = 0.
- Plan-close commits: 01 `0909167`/`a25c89b`; 02 `cab2112`/`923132e`; 03 `d495cfa`/`22694f6`; 04 `29120da`/`1582e5a` (+ remediation `1b7b9ca`,`5d3b305`,`9458cb8`); 05 `1b5ff10`/`c8e662b` (+ corrective 023).

**Key runtime anchors**
- App assembly: `code/backend/app/main.py:36-71` (13 routers, RequestID middleware, two exception handlers, startup migrations).
- Migration registry: `code/backend/app/db/migrate.py:23-41` (operative), `db/migrations/__init__.py` (parallel convenience list, consistent).
- Money paths: `services/payments/funding_coordinator.py` (persist/fund/reconcile: 95-259, 325-435, 571-699), `services/payments/release_coordinator.py` (128-232, 252-332), `services/settlement.py` (159-246 legacy, 249-563 account), `services/ratifications.py:234` (runtime funding trigger).
- Constraints: `db/migrations/016_funding_units_provider_payments.py:16-96` (uniques/checks quoted in §5).
- Findings anchors: `routers/evidence_submit.py:14,196,229-232`; `settlement.py:349-355,461-489`; `config.py:49,68,110-112`; `routers/approvals.py:69-156`; `services/payment_provider.py:182-187`; `services/evidence_records.py:262`.

**Commands executed (verification, not modification)**
```text
git log/rev-list/branch/merge-base archaeology (see above)
git archive 3ec9e8c | tar -x  → isolated baseline snapshot analysis
cd code && ./.venv/Scripts/python.exe -m pytest -q  → 896 passed, 1 skipped, 32 warnings (31.60s)
grep sweeps: evaluate_settlement / verify_evidence / legacy_compat / emit( / audit.record( /
             logger|print / CORSMiddleware / password_hash / PAN|CVC|CVV|CardNumber …
```

**Delegated sweep conclusions incorporated:** runtime wiring inventory (no orphan routers/services/repositories; provider-factory divergence B-5; approvals flag gap B-4), security sweep (§12), test/CI inventory (§10), baseline reconstruction (§3/§5).
