# 08B2 — Frontend Slice B2: Rules and Ratification (PR 2)

> **Durum:** Uygulandı — 2026-07-12 · Sapmalar: redacted tax-id parent-preservation uyumluluk düzeltmesi eklendi; browser smoke kısmi yapıldı. · **Master:** `plans/done/08_frontend_completion_master_plan.md`
> **Readiness:** `READY_TO_IMPLEMENT` (frontend PR 1 base still required). The backend contract gap closure is complete; the frontend plan itself remains ready, not done.

## A. Phase identity

- **PR title:** `feat(frontend): Slice B2 — rules, reviews, tracking policy and ratification`
- **Branch:** `feat/frontend-rules-ratification`
- **Base:** the integration base per master plan §1 (`program/domain-evolution-v2`, or `master` once it contains `ebf6dc7`), **after PR 1 (`feat/frontend-deal-core`) is merged into it**
- **Prerequisite merged PR:** PR 1; plus backend resolution of blockers **B1** (account tracking-policy configure/lock endpoints) and **B2** (account rule-set version read/list endpoint) — both are backend work outside this PR
- **Included scope:** `rules` section (extracted-vs-declared party comparison, validator findings, review case list + actions, rule revision + revalidation, rule-set version list/diff); `ratification` section (tracking-policy selection/locking, package build/projection, package hash, funding schedule/units/tranches, release mode, buyer+seller ratification, funding/activation visibility); status-map and event-label extensions.
- **Excluded scope:** evidence upload, disputes, payments, bundle/snapshot (PR 3); any legacy view; any backend change.
- **Expected commits (exactly 3):**
  1. `feat(frontend): reviews and party comparison (rules section)` — types/api for reviews, rules section page with comparison + findings + review actions.
  2. `feat(frontend): rule revision and revalidation` — revision form, version list/diff (depends on B2 contract).
  3. `feat(frontend): tracking policy and ratification` — policy panel (depends on B1 contract), package view + ratify, doc-sync.

## B. Contract-drift preflight

1. **Blocker gate (must pass, else stay BLOCKED):**
   a. **B1:** Search `code/backend/app/routers/` for a session-authenticated account_v2 tracking-policy configure/lock pair (expected shape: `PUT/POST` under `/api/transactions/{id}/tracking-policy*` guarded by `require_authenticated_user` + `require_csrf_protection`, NOT by `manager_token` body field). Record its exact request/response/error contract into §C-TP below before coding.
   b. **B2a:** Search for a session-authenticated read exposing the current rule-set version id (and the version list) for a transaction (candidate shapes: `GET /api/transactions/{id}/rule-sets` or an added `rule_set` block in `GET /api/transactions/{id}`). Record its contract into §C-RS0.
   c. **B2b:** Verify a safe `source_quote` semantics for revisions exists — either (i) the revision endpoint now accepts `source_quote` as optional and documents parent-preservation for omitted quotes, or (ii) the B2a read provides a creator-manager-only full (unredacted-quote) edit projection. Confirm in `routers/rule_sets.py`/`services/rule_versions.py` + tests. **Submitting empty or masked quote strings is FORBIDDEN — it would permanently destroy contract citations in the new immutable version.**
   If any of a–c is still missing, STOP: report `BLOCKED — B1/B2a/B2b unresolved` and do not implement the affected tasks (Tasks 4–7); Tasks 1–3 (reviews + comparison) may proceed only if the team explicitly asks for a partial PR — default is stop.
2. `code/backend/app/routers/reviews.py` — routes/codes per §C1–C2 unchanged; `schemas/reviews.py` enums unchanged.
3. `code/backend/app/routers/rule_sets.py` — revision/validate routes, `RuleSetVersionPublicView` fields, 403 `RULE_REVISION_FORBIDDEN`, 409 codes (`STALE_RULE_SET_VERSION`, `RULE_REVISION_AFTER_RATIFICATION`, `RULE_REVISION_NOT_ALLOWED`, `LEGACY_RULE_REVISION_FORBIDDEN`, `RULE_REVISION_CONFLICT`, `PACKAGE_INTEGRITY_FAILED`) unchanged.
4. `code/backend/app/routers/ratifications.py` — three routes; build 403 `RATIFICATION_PACKAGE_AMENDMENT_FORBIDDEN`; readiness reason codes in `services/ratification_package.py` (`RULE_SET_NOT_READY`, `RULE_SET_NOT_RATIFIABLE`, `PARTICIPANTS_NOT_CONFIRMED`, `PARTICIPANTS_NOT_BOUND`, `SAME_LEGAL_ENTITY`, `TRACKING_POLICY_NOT_LOCKED`, `BLOCKING_REVIEW`); ratify codes per §C7.
5. `code/backend/app/schemas/ratification.py` (`RatificationPackagePublicView`, `RatificationOutcome`), `schemas/payments.py` (`FundingScheduleSpec`, `MilestoneReleaseOverride`, `RequestedReleaseMode`), and `services/ratification_package.py::_funding_plan_payload` (canonical payload `funding_schedule` shape) unchanged.
6. `code/backend/app/schemas/extraction.py` — `ExtractionJSON` field set matches §F `ExtractionJSONInput` (structural snapshot test `tests/test_extraction_schema.py` is the authority).
7. Frontend: PR 1 files exist per 08b1 §O; `TransactionShell` outlet context `{detail, refresh, loading, error}`; section registry currently `["overview","parties"]`.

**Acceptable drift:** added optional fields; extra readiness reason codes (render code as text fallback). **Stop:** changed route paths/methods, changed `package_hash`/`canonical_payload` location, revision body no longer full `ExtractionJSON`.

## C. Verified contract table

### C1 `GET /api/transactions/{id}/reviews`
- Auth: session; active assignment OR platform reviewer/admin. CSRF: no. AE: not required.
- Response 200: `Array<{case: ReviewCase, actions: ReviewAction[]}>` — `ReviewCase` = `{id, transaction_id, phase: "pre_ratification"|"settlement"|"payment", source_type: "validator"|"party_mismatch"|"evidence"|"video"|"payment"|"system", source_id: string|null, reason_code, title, description, severity: "warning"|"blocking", status: "open"|"evidence_requested"|"resolved"|"escalated"|"cancelled", assigned_to_user_id, opened_by_actor_type, opened_by_user_id, resolved_by_user_id, resolution_code, resolution_note, created_at, resolved_at}`; `ReviewAction` = `{id, review_case_id, actor_user_id, acting_entity_id, action, payload: object|null, created_at}`.
- Errors: 401 · 403 `REVIEW_ACCESS_DENIED`. Read, retry-safe. Evidence: `routers/reviews.py:81-97`, `tests/test_reviews_router.py`.

### C2 `POST /api/reviews/{review_case_id}/actions`
- Auth: session. CSRF: yes. AE: required for `escalate_dispute` (approver check binds `acting_entity_id`).
- Request: `{action: "comment"|"request_evidence"|"resolve_continue"|"resolve_reject"|"escalate"|"escalate_dispute"|"cancel", comment?: string ≤2000, resolution_code?: string ≤64 (A-Z0-9_ only)}`.
- Authorization matrix (backend-enforced): `comment` → manager/approver/platform; `escalate_dispute` → buyer/seller participant approver only; all other actions → platform reviewer/admin only.
- Response 200: `ReviewAction`.
- Errors: 400 `REVIEW_COMMENT_REJECTED` (PII/token-like content) · 403 `REVIEW_ACTION_FORBIDDEN` · 404 `REVIEW_CASE_NOT_FOUND` · 409 `REVIEW_CASE_CLOSED`, `REVIEW_ACTION_NOT_ALLOWED` (blocking non-pre_ratification bypass; payment cases without operation success), `REVIEW_RESOLUTION_PRECONDITION_FAILED`.
- Side effects: `resolve_continue` on blocking pre_ratification returns transaction to `preparation`; resolve/cancel re-trigger settlement (account). Settlement video cases accept only `resolution_code ∈ {VIDEO_FALSE_POSITIVE, SUPERSEDED_BY_CLEAN_EVIDENCE}`.
- Not idempotent (append-only log); repeat of terminal action → 409 `REVIEW_CASE_CLOSED`.
- Evidence: `routers/reviews.py:100-157`, `services/review.py`, `tests/test_review_resolution_e2e.py`.

### C-RS0 Current rule-set version read — **CONTRACT MISSING (blocker B2)**
Required by the frontend to obtain `version_id` for C3/C4 and to render the version list/diff. No such endpoint exists at HEAD `ebf6dc7` (verified: detail returns only redacted extraction + `{status, findings}`; `RuleSetVersionPublicView` is only a *response* of C3/C4; package payload carries `rule_set.id` but exists only post-policy-lock). Fill in from the real backend contract during preflight 1b.

### C3 `POST /api/transactions/{id}/rule-sets/{version_id}/revisions`
- Auth: session; **creator-side manager**: active manager assignment whose `legal_entity_id == transactions.owner_entity_id` AND `X-Acting-Entity-ID == owner_entity_id`. CSRF: yes.
- Request: **full `ExtractionJSON`** (§4.2 — see §F `ExtractionJSONInput`). Response 200: `RuleSetVersionPublicView` `{id, transaction_id, version, parent_version_id, extraction (redacted, no source_quote), rules_hash, validator_status, validator_report: [{code, severity}]|null, status, created_by_user_id, created_at}`.
- Lifecycle: only account_v2 + state ∈ {preparation, awaiting_review, awaiting_approval, awaiting_ratification}; parent must be current (CAS). New version auto-validated; NEEDS_REVIEW opens blocking validator case; existing package superseded/updated fail-closed.
- Errors: 403 `RULE_REVISION_FORBIDDEN` · 404 `TRANSACTION_NOT_FOUND`, `RULE_SET_NOT_FOUND` · 409 `LEGACY_RULE_REVISION_FORBIDDEN`, `RULE_REVISION_AFTER_RATIFICATION`, `RULE_REVISION_NOT_ALLOWED`, `STALE_RULE_SET_VERSION`, `RULE_REVISION_CONFLICT`, `PACKAGE_INTEGRITY_FAILED`, `PACKAGE_INPUTS_INVALID` · 422 pydantic for malformed payload.
- Not idempotent; on 409 stale → refresh current version and let the user re-apply.
- Evidence: `routers/rule_sets.py:372-392`, `tests/test_rule_revision_endpoints.py`.

### C4 `POST /api/transactions/{id}/rule-sets/{version_id}/validate`
- Same auth/CSRF/lifecycle gates as C3; only the **current** version may be revalidated. Empty body. Response: `RuleSetVersionPublicView`. Errors: as C3 minus revision-specific; plus 404 `RULE_SET_NOT_FOUND`. Deterministic → repeat-safe. Old blocking review is NOT auto-closed by a PASS.
- Evidence: `routers/rule_sets.py:395-444`.

### C-TP Tracking policy configure/lock (account) — **CONTRACT MISSING (blocker B1)**
Required flow: manager reviews system recommendation (`recommendation`, `recommendation_reason_codes`), sets `physical_delivery_confirmed` + `tracking_mode ∈ {off, document_only, document_and_video}`, then locks; contractual `required_evidence` may force `document_and_video` (409 `POLICY_CONTRACT_CONFLICT` family per legacy semantics). The only existing endpoints are legacy `manager_token`-bodied (`routers/transactions.py:672,729`) and unusable for account rows. Fill in the real contract during preflight 1a; expected UI is specified in §H row "PolicyPanel" against the legacy semantic model (same conflict codes: `POLICY_NOT_CONFIGURABLE`, `POLICY_LOCKED`, `POLICY_INVALID`, `POLICY_CONTRACT_CONFLICT`).

### C5 `POST /api/transactions/{id}/ratification-packages`
- Auth: session; creator-side manager (same rule as C3). CSRF: yes. Request: `{funding_schedule_spec?: {overrides: [{rule_index: int ≥0, release_mode: "all_or_nothing"|"fixed_tranches"|"proportional_to_verified_quantity", tranche_count?: int ≥1}]}}` (default `{}` → all milestones `all_or_nothing`; `proportional_to_verified_quantity` is always rejected by the Moka profile — expose only the two supported modes in the form, keep the third documented).
- Behavior: builds (or returns existing) current package; if inputs changed since last package → supersede + rebuild; then opens it (`status: "open"`). Response 200: `RatificationPackagePublicView` `{id, transaction_id, version, status: "draft"|"open"|"complete"|"superseded"|"cancelled", package_hash, canonical_payload: CanonicalPackagePayload, created_at, opened_at, completed_at}`.
- Errors: 403 `RATIFICATION_PACKAGE_AMENDMENT_FORBIDDEN` · 404 `TRANSACTION_NOT_FOUND`, `PACKAGE_NOT_FOUND` · 409 readiness codes `DOCUMENT_NOT_READY`/`RULE_SET_NOT_READY`/`RULE_SET_NOT_RATIFIABLE`/`PARTICIPANTS_NOT_CONFIRMED`/`PARTICIPANTS_NOT_BOUND`/`SAME_LEGAL_ENTITY`/`TRACKING_POLICY_NOT_LOCKED`/`BLOCKING_REVIEW`/`PACKAGE_INPUTS_CHANGED`/`PACKAGE_INTEGRITY_FAILED` + funding-plan compile codes (e.g. `PROVIDER_CAPABILITY_CONFLICT`, `MOKA_REQUIRES_FIXED_FUNDING_UNITS`) — render code-keyed Turkish copy with raw-code fallback.
- Idempotent for unchanged inputs (returns same package/hash). Evidence: `routers/ratifications.py:137-180`, `tests/test_ratification_package.py`.

### C6 `GET /api/transactions/{id}/ratification-packages/current`
- Auth: session; any active assignment. CSRF: no. Response 200: `RatificationPackagePublicView` (identical projection + `package_hash` for both parties — render hash prominently). Errors: 403 `TRANSACTION_ACCESS_DENIED` · 404 `PACKAGE_NOT_FOUND` (no package yet — expected pre-build state, render EmptyState not error). Read, retry-safe.
- `canonical_payload` keys used by UI: `funding_schedule {currency, total_amount_minor, milestones: [{rule_index, title, trigger_type, basis_points, amount_minor, currency, required_evidence[], release_mode, funding_units: [{sequence, amount_minor, eligibility_type, eligibility_payload}]}]}`, `commercial_summary {currency, total_amount_minor, delivery_deadline, goods[]}`, `tracking_policy.snapshot`, `rule_set {id, version, rules_hash}`, `package_schema_version`, `provider_profile`.
- Evidence: `routers/ratifications.py:183-195`, `services/ratification_package.py:309-341`.

### C7 `POST /api/ratification-packages/{package_id}/ratifications`
- Auth: session; actor must be a bound buyer/seller participant of the package's transaction (via own assignment); acts only for own participant/entity. CSRF: yes. Request: empty body.
- Response 200: `{ratification: {id, package_id, transaction_id, participant_id, user_id, legal_entity_id, participant_role, auth_method, approved_at, ...}, package_status, funding_triggered: bool}`.
- Idempotent per (package, participant): replay returns existing ratification, `funding_triggered:false`. Second party's success → package `complete` + funding coordinator runs (**provider side effects: pool payments are created**) → `funding_triggered:true`; state → `funding_pending` or `active`.
- Errors: 403 `RATIFICATION_NOT_AUTHORIZED` (not a participant; same user both sides) · 404 `PACKAGE_NOT_FOUND` · 409 `PACKAGE_NOT_OPEN`, `PACKAGE_SUPERSEDED`, `PACKAGE_CANCELLED`, `PACKAGE_ALREADY_COMPLETE`, `PACKAGE_INTEGRITY_FAILED`, `FUNDING_COORDINATOR_CONFLICT`.
- Retry: do NOT auto-retry (financial trigger). On network failure instruct refresh of package (idempotency makes a repeat safe *after* user confirms state).
- Evidence: `routers/ratifications.py:198-223`, `services/ratifications.py:133-239`, `tests/test_ratifications.py`.

## D. Blocking and non-blocking gaps

**Blockers (prevent implementation of mandated scope):**
1. **B1 — no account tracking-policy configure/lock API** (master §14.1). Without it: policy UI impossible AND the whole ratification flow undemonstrable (`TRACKING_POLICY_NOT_LOCKED` 409 on build). Needs backend PR; this plan's PolicyPanel spec (§H) is written against the expected semantics so only the fetch layer needs the final route/fields.
2. **B2 — no read exposes current rule-set `version_id` or version history.** Without it: revision/revalidate calls cannot be constructed; "version list + diff" has no data source. Needs backend read endpoint.

**Inconsistencies the frontend can safely normalize:**
- Package 404 before build = normal pre-state (EmptyState, not error).
- Readiness 409 codes are the UI's checklist: map each code to a Turkish checklist row ("Taraf profilleri onaylanmadı", "Takip politikası kilitlenmedi", "Engelleyici inceleme açık"...), unknown code → raw code row.
- Review `payload` objects: render only known keys (`comment`, `resolution_code`, `review_case_id`, `instruction_id`, `operation_type`); never dump.

**Unsupported states requiring clear UI:** `PACKAGE_SUPERSEDED` on ratify → banner "Paket girdiler değiştiği için yenilendi; güncel paketi inceleyip yeniden onaylayın" + refresh; blocking `settlement`/`payment` cases shown read-only for non-platform users (actions 403).

**Assumptions never to make:** never compute `package_hash`/funding schedule client-side; never pre-filter review actions by guessed role (attempt → 403 render); never treat `funding_triggered:false` replay as failure; never enable ratify from local ratification memory — only from fresh package/bundle projections.

## E. Route changes

- Created: `/transactions/:transactionId/rules`, `/transactions/:transactionId/ratification` (both inside existing shell; RequireAuth inherited).
- Extended: `TransactionShell` section registry → `["overview","parties","rules","ratification"]`; `lib/statusMaps.ts` gains `reviewStatusMap`, `reviewSeverityMap`, `packageStatusMap`, `policyStatusMap`; `lib/eventLabels.ts` confirms labels for `rule_set_revised`, `rules_validated`, `tracking_policy_updated`, `tracking_policy_locked`, `funding_required`, `funding_units_pool_created`.
- No redirects, no token behavior changes. Route-level loading/failure per shell pattern; section-local reads render their own Loading/Retry panels.

## F. Exact TypeScript types

`src/types/reviews.ts`: `ReviewPhase`, `ReviewSourceType`, `ReviewSeverity`, `ReviewStatus`, `ReviewActionType` (string unions per C1), `ReviewCase`, `ReviewAction`, `ReviewCaseWithActions { case: ReviewCase; actions: ReviewAction[] }`, `ReviewActionRequest { action: ReviewActionType; comment?: string; resolution_code?: string }`.

`src/types/rules.ts`: `RuleSetStatus = "draft"|"validated"|"ratifiable"|"superseded"|"ratified" | (string & {})`; `RuleSetVersionPublicView { id; transaction_id; version: number; parent_version_id: string|null; extraction: RedactedExtraction; rules_hash: string; validator_status: string|null; validator_report: {code: string; severity: string}[]|null; status: RuleSetStatus; created_by_user_id: string|null; created_at: string }`; `ExtractionJSONInput` — full §4.2 shape:
```ts
export interface ExtractionJSONInput {
  contract_id: string;
  parties: { buyer: { name: string; tax_id: string | null }; seller: { name: string; tax_id: string | null } };
  commercial_terms: { currency: "TRY"|"USD"|"EUR"|"OTHER"; total_amount: number; goods: { name: string; quantity: number; unit: string }[]; delivery_deadline: string | null };
  payment_rules: { milestone: string; trigger: "approval"|"e_invoice"|"delivery_video"|"manual_review"; percentage: number; required_evidence: ("contract"|"e_irsaliye"|"video")[]; source_quote: string; confidence: number }[];
  risk_flags: string[];
  needs_manual_review: boolean;
}
```
(plus whatever the B2 read returns — add `RuleSetVersionSummary` from the preflight-recorded contract).

`src/types/ratification.ts`: `RatificationPackageStatus`, `FundingUnitSpec { sequence: number; amount_minor: number; eligibility_type: string; eligibility_payload: Record<string, unknown> }`, `FundingScheduleMilestone { rule_index: number; title: string; trigger_type: string; basis_points: number; amount_minor: number; currency: string; required_evidence: string[]; release_mode: "all_or_nothing"|"fixed_tranches"; funding_units: FundingUnitSpec[] }`, `CanonicalPackagePayload` (keys per C6), `RatificationPackagePublicView`, `MilestoneReleaseOverride { rule_index: number; release_mode: string; tranche_count?: number }`, `FundingScheduleSpecInput { overrides: MilestoneReleaseOverride[] }`, `RatificationView`, `RatificationOutcome { ratification: RatificationView; package_status: RatificationPackageStatus; funding_triggered: boolean }`.

`src/types/tracking.ts` (fields per legacy `schemas/tracking.py`, to be confirmed against the B1 endpoint): `TrackingMode = "off"|"document_only"|"document_and_video"`, `TrackingPolicyView { recommendation: "yes"|"no"|"uncertain"; recommendation_reason_codes: string[]; manager_physical_delivery_confirmed: boolean|null; tracking_mode: TrackingMode; video_role: "advisory"; status: "draft"|"locked"; configured_at: string|null; locked_at: string|null }`, `PolicyConflictDetail { code: string; message: string; conflicts: string[] }`.

## G. Exact API functions

`src/api/reviews.ts`: `listReviews(transactionId): Promise<ReviewCaseWithActions[]>` — GET, no csrf; `submitReviewAction(reviewCaseId, body: ReviewActionRequest): Promise<ReviewAction>` — POST, csrf, `redirectOnError:false`; expected errors per C2.

`src/api/rules.ts`: `createRuleRevision(transactionId, versionId, payload: ExtractionJSONInput): Promise<RuleSetVersionPublicView>` — POST `/transactions/${transactionId}/rule-sets/${versionId}/revisions`, csrf; `validateRuleVersion(transactionId, versionId): Promise<RuleSetVersionPublicView>` — POST `.../validate`, csrf; plus the B2 read function (e.g. `getRuleSetVersions(transactionId)`) — exact URL from preflight.

`src/api/tracking.ts` (B1): `getTrackingPolicy(transactionId)` / `updateTrackingPolicy(transactionId, body)` / `lockTrackingPolicy(transactionId)` — exact URLs/fields from preflight; all mutations csrf, `redirectOnError:false`; 409 bodies may be `PolicyConflictDetail` in `error.detail` — parse with a typed guard `parsePolicyConflict(detail: unknown): PolicyConflictDetail | null`.

`src/api/ratification.ts`: `buildRatificationPackage(transactionId, body: {funding_schedule_spec?: FundingScheduleSpecInput})` — POST, csrf; `getCurrentRatificationPackage(transactionId)` — GET, `redirectOnError:false` (404 is a normal state); `submitRatification(packageId)` — POST `/ratification-packages/${packageId}/ratifications`, csrf.

## H. Page and component tree

| File | Component | Spec |
|---|---|---|
| `pages/transactions/TransactionRulesPage.tsx` | `TransactionRulesPage` | Reads (parallel): shell detail (context), `listParticipants`, `listReviews`, B2 version read. Blocks: **PartyComparisonPanel**, **ValidatorFindingsPanel**, **RuleVersionsPanel**, **ReviewCasesPanel**. |
| `pages/transactions/rules/PartyComparisonPanel.tsx` | `PartyComparisonPanel` | Props: `extraction: RedactedExtraction\|null`, `participants: ParticipantPublicView[]`, `mismatchCases: ReviewCase[]` (filtered `source_type==="party_mismatch"`). Two columns buyer/seller: extracted name (from extraction.parties) vs participant `display_name` + status badge; open mismatch case rows underneath (reason_code, severity, status). Empty: "Karşılaştırma için extraction bekleniyor". No client-side diffing beyond string display — mismatch truth comes from review cases. |
| `pages/transactions/rules/ValidatorFindingsPanel.tsx` | `ValidatorFindingsPanel` | Props: `validator: ValidatorReport\|null`. Status badge + findings table (code, severity, message when present). |
| `pages/transactions/rules/RuleVersionsPanel.tsx` | `RuleVersionsPanel` | **BLOCKED until B2.** Props: `versions: RuleSetVersionSummary[]`, `currentVersionId`. Version table (version, status, validator_status, created_at, rules_hash short); "Diff" = side-by-side of the two selected versions' `extraction` rendered through a pure `diffExtraction(a, b)` helper producing field-level changed/added/removed rows (payment_rules keyed by index; goods by index; scalar fields by path) — display-only, no semantic judgment. Revision form: full-form editor prefilled from current version's extraction (fields per `ExtractionJSONInput`; `source_quote` fields default `""` for redacted reads — flag in helper text that quotes are not shown and are preserved server-side only if re-entered; this is a documented consequence of the redacted read, confirm exact behavior of B2 contract in preflight). Submit → `createRuleRevision(current.id, payload)`; 409 `STALE_RULE_SET_VERSION` → refresh + banner. Revalidate button per current version. Only rendered when shell state ∈ pre-ratification set; otherwise Notice "Ratification sonrası kurallar değiştirilemez". |
| `pages/transactions/rules/ReviewCasesPanel.tsx` | `ReviewCasesPanel` | Props: `cases: ReviewCaseWithActions[]`, `onAction(caseId, body)`, `busyCaseId`. Case cards: title, reason_code, phase/source badges, severity/status badges, description, action `Timeline` (actor id short, action label, safe payload keys), then a `CommandPanel`: action select (all 7 actions — do not pre-filter; helper text explains typical authorization), comment textarea, resolution_code input shown for resolve actions (with quick-pick chips `VIDEO_FALSE_POSITIVE`, `SUPERSEDED_BY_CLEAN_EVIDENCE` for settlement/video cases). Errors rendered per C2 code map (`reviewActionErrorMessage`). Success → refresh reviews + `shell.refresh()`. |
| `pages/transactions/TransactionRatificationPage.tsx` | `TransactionRatificationPage` | Reads (sequenced): shell context; `getCurrentRatificationPackage` (404 → no-package state); policy read (B1). Blocks: **PolicyPanel**, **PackagePanel**, **RatifyPanel**. |
| `pages/transactions/ratification/PolicyPanel.tsx` | `PolicyPanel` | **BLOCKED until B1.** Shows recommendation + reason codes (Turkish map + raw fallback), contractual required evidence (from extraction.payment_rules union — display only), mode radio (off/document_only/document_and_video) + physical-delivery-confirmed checkbox, Save (update) and Lock (ConfirmDialog: "Kilitlendikten sonra politika değiştirilemez") commands; 409 `PolicyConflictDetail` renders `conflicts[]` as list; locked state → read-only summary with locked_at. Contractual-video conflict copy for `POLICY_CONTRACT_CONFLICT`. |
| `pages/transactions/ratification/PackagePanel.tsx` | `PackagePanel` | Props: `pkg: RatificationPackagePublicView\|null`, `onBuild(spec)`, `canBuildHint`. No package → build form: per-milestone release-mode override rows (rule_index select from extraction.payment_rules, mode select `all_or_nothing`/`fixed_tranches`, tranche_count number ≥2 when tranches) + build button; 409 readiness codes → checklist (§D). Package present → **hash block** (full `package_hash` monospace + copy button + "İki taraf da aynı hash'i görmelidir"), status badge, version, `commercial_summary` grid, **funding schedule table** per milestone (title, trigger, %, amount `formatAmountMinor`, release_mode, required evidence) with nested unit rows (sequence, amount, eligibility_type); tracking-policy snapshot summary; superseded banner when `status==="superseded"`. Rebuild button (creator manager; others get 403 rendered). |
| `pages/transactions/ratification/RatifyPanel.tsx` | `RatifyPanel` | Props: `pkg`, `ratifications` (from PR 3's bundle in future; in PR 2 derive display from ratify responses + package `status==="complete"`), `onRatify`. Shows selected acting entity, ConfirmDialog ("‘Onayla’ hukuki taahhüt niteliğindedir; paket hash'i: …"), result: own ratification recorded; `funding_triggered:true` → success Notice "Fonlama başlatıldı" + `shell.refresh()`; 409 map per C7 (`PACKAGE_SUPERSEDED` → refresh package; `PACKAGE_ALREADY_COMPLETE` → info). Disabled when no package/`status!=="open"` with reason text. |

Loading/empty/error/permission/conflict/responsive/a11y: shared patterns (master §5, §8–§10); every panel has explicit empty & 403 rendering.

## I. Data loading and mutation refresh

| Page | Initial reads | Ordering | Refresh triggers |
|---|---|---|---|
| Rules | participants ∥ reviews ∥ versions(B2); detail from context | parallel | review action → reviews + shell; revision/validate → versions + reviews + shell; manual "Yenile" |
| Ratification | policy(B1) ∥ current package; detail from context | parallel | policy save/lock → policy (+package refresh, inputs changed); build → package; ratify → package + shell; 409 anywhere → offer refresh |

Failures: per-panel `RetryPanel`; mutations inline `FormError`; no polling in either section (post-ratify funding progress is visible via overview polling? — no: overview polls only uploaded/extracting; funding progress is manual refresh by design, master §8). Cancellation: `useAsyncData` guard. Stale: 409 → banner + refresh CTA, never auto-retry.

## J. Lifecycle and action matrix

| State | Rules section | Ratification section |
|---|---|---|
| `uploaded`/`extracting` | comparison empty-state; reviews list (usually empty) | build disabled: "Extraction tamamlanmadı" (backend 409 `RULE_SET_NOT_READY` if attempted) |
| `awaiting_review` | validator NEEDS_REVIEW findings; blocking validator case actionable (platform resolves; manager comments); revision form enabled | build → 409 `BLOCKING_REVIEW`/`RULE_SET_NOT_RATIFIABLE` rendered as checklist |
| `preparation` (post-resolve) | revision + revalidate enabled | build enabled once readiness met |
| `awaiting_approval` | revision enabled | policy configure/lock (B1); build once policy locked |
| `awaiting_ratification` | revision still allowed (supersedes package — warn in form) | package view + ratify enabled (`status==="open"`) |
| `funding_pending` | revision blocked (409 `RULE_REVISION_AFTER_RATIFICATION`) | package complete; ratify replay idempotent; funding progress via events (overview) |
| `active`/`settled` | read-only panels | package read-only, hash still displayed |
| `rejected`/`cancelled` | read-only + validator REJECT explanation | build disabled with reason |

Backend-owned, never derived: readiness, package hash, funding schedule math, who may act, policy conflict rules.

## K. Execution task packets

#### Task 1 — Reviews types + API + status maps
**Goal** typed reviews layer ready.
**Depends on** PR 1 merged.
**Files to create** `src/types/reviews.ts`, `src/api/reviews.ts`, `src/api/reviews.test.ts`
**Files to modify** `src/lib/statusMaps.ts` (add `reviewStatusMap`, `reviewSeverityMap`, `reviewPhaseMap`, `reviewSourceMap`), `src/lib/statusMaps.test.ts`
**Required changes** per §F/§G/C1–C2.
**Must not change** existing maps' keys/labels; `api/client.ts`.
**Tests to add or update** api test: list parse, action POST with csrf, 403/409 code passthrough; maps completeness.
**Verification commands** `cd code/frontend && npm run lint && npm run typecheck && npm run test`
**Done when** green.

#### Task 2 — Rules section: comparison + findings + review panel
**Goal** `/transactions/:id/rules` live (without versions panel).
**Depends on** Task 1
**Files to create** `pages/transactions/TransactionRulesPage.tsx`, `pages/transactions/rules/{PartyComparisonPanel,ValidatorFindingsPanel,ReviewCasesPanel}.tsx`, `pages/transactions/rules/rulesLogic.ts`, `pages/transactions/rules/rulesLogic.test.ts`
**Files to modify** `components/TransactionShell.tsx` (registry + route), `routes/AppRoutes.tsx`, `pages/index.ts`
**Required changes** per §H; `rulesLogic.ts` pure helpers: `splitCasesBySource(cases)`, `reviewActionErrorMessage(code)`, `safeActionPayloadEntries(payload)` (allowlist `comment,resolution_code,review_case_id,instruction_id,operation_type`).
**Must not change** overview/parties pages.
**Tests to add or update** `rulesLogic.test.ts`: payload allowlist (feed `token`-keyed payload → dropped), error map incl. unknown, case splitting.
**Verification commands** lint/typecheck/test/build
**Done when** green; section renders against backend with a NEEDS_REVIEW fixture.

#### Task 3 — Ratification types + API
**Goal** typed package/ratify layer.
**Depends on** Task 1
**Files to create** `src/types/ratification.ts`, `src/api/ratification.ts`, `src/api/ratification.test.ts`
**Files to modify** `src/lib/statusMaps.ts` (`packageStatusMap`), `src/lib/eventLabels.ts` (verify funding labels exist)
**Required changes** per §F/§G/C5–C7.
**Tests** api test: current-package 404 → typed null-state handling helper `isNoPackageError(err)`; build 409 readiness code extraction; ratify idempotent replay shape.
**Verification commands** lint/typecheck/test
**Done when** green.

#### Task 4 — [GATED B1] Tracking policy types + API + PolicyPanel
**Goal** policy configure/lock UI.
**Depends on** preflight 1a recorded contract.
**Files to create** `src/types/tracking.ts`, `src/api/tracking.ts`, `pages/transactions/ratification/PolicyPanel.tsx`, `pages/transactions/ratification/policyLogic.ts` + test
**Required changes** per §C-TP/§H; `policyLogic.ts`: `parsePolicyConflict`, `policyConflictMessage(code)`, `reasonCodeLabel(code)`.
**Must not change** legacy endpoints usage — never call `manager_token` endpoints.
**Tests** conflict detail parsing (object vs string detail), message maps.
**Done when** green + panel drives a real policy to `locked` in dev.

#### Task 5 — Ratification section: PackagePanel + RatifyPanel + page
**Goal** `/transactions/:id/ratification` live.
**Depends on** Tasks 3 (+4 for the policy block; if B1 slips after code start, render policy block behind `null`-guard EmptyState "Politika API'si bekleniyor" — only with explicit team approval, default is blocked).
**Files to create** `pages/transactions/TransactionRatificationPage.tsx`, `pages/transactions/ratification/{PackagePanel,RatifyPanel}.tsx`, `pages/transactions/ratification/packageLogic.ts` + test
**Files to modify** shell registry, `routes/AppRoutes.tsx`, `pages/index.ts`
**Required changes** per §H; `packageLogic.ts`: `readinessChecklist(code)` map, `scheduleRows(payload)` flattener (pure), `buildSpecFromForm(rows)` validating tranche_count ≥2 for fixed_tranches.
**Tests** checklist map incl. unknown; scheduleRows on the §C6 fixture shape; spec builder validation.
**Done when** green; both-party ratify flow demonstrated in dev (after B1).

#### Task 6 — [GATED B2] Rule versions panel + revision form
**Goal** version list/diff + revision/revalidate UI.
**Depends on** preflight 1b recorded contract; Task 2.
**Files to create** `src/types/rules.ts`, `src/api/rules.ts`, `pages/transactions/rules/RuleVersionsPanel.tsx`, `pages/transactions/rules/ruleDiff.ts`, `pages/transactions/rules/revisionForm.ts` + tests for both
**Files to modify** `TransactionRulesPage.tsx` (add panel + version read)
**Required changes** per §C3/C4/C-RS0/§H; `ruleDiff.ts` pure structural diff; `revisionForm.ts` builds `ExtractionJSONInput` from form state with numeric coercion + validation mirroring pydantic types (client-side pre-check only; backend remains authority).
**Tests** diff on crafted version pairs (changed rule %, added good, removed flag); form builder rejects percentage outside 0–100 only if backend does (do NOT invent constraints — mirror §4.2 types only: numbers are numbers); stale-409 message.
**Done when** green; revision produces new version in dev and validator case appears.

#### Task 7 — Docs + doc-sync + final pass
**Goal** README route list + ARCHITECTURE frontend routes updated; suite green.
**Depends on** all above.
**Files to modify** `code/frontend/README.md`, `ARCHITECTURE.md` (frontend route list line only), this plan status block.
**Verification commands** §N.
**Done when** §N green; manifest matches §O.

## L. Test matrix

| Scenario | Where |
|---|---|
| Reviews list parse; action POST csrf; empty list | `api/reviews.test.ts` |
| Review action 400 `REVIEW_COMMENT_REJECTED` / 403 / 404 / 409 (`REVIEW_CASE_CLOSED`, `REVIEW_ACTION_NOT_ALLOWED`, `REVIEW_RESOLUTION_PRECONDITION_FAILED`) → distinct copy | `rulesLogic.test.ts` |
| Action payload allowlist redaction (token-like keys dropped) | `rulesLogic.test.ts` |
| Package current 404 → no-package state (not error) | `api/ratification.test.ts` |
| Build 409 readiness codes → checklist rows; unknown code fallback | `packageLogic.test.ts` |
| Ratify success / replay idempotent (`funding_triggered:false`) / `PACKAGE_SUPERSEDED` / `PACKAGE_ALREADY_COMPLETE` / `FUNDING_COORDINATOR_CONFLICT` | `api/ratification.test.ts` + `packageLogic.test.ts` |
| Network failure on ratify → "durumu yenileyin, tekrar denemeden önce" copy | `packageLogic.test.ts` |
| Invalid response (non-envelope 500) → generic | api tests |
| Policy conflict detail parsing (`PolicyConflictDetail` vs string) + `POLICY_CONTRACT_CONFLICT` copy | `policyLogic.test.ts` |
| Rule diff correctness; revision stale 409; revalidate repeat-safe | `ruleDiff.test.ts`, `revisionForm.test.ts` |
| Lifecycle gating: revision blocked states → 409 code map (`RULE_REVISION_AFTER_RATIFICATION` etc.) | `rulesLogic.test.ts` |
| Authorization-dependent visibility: 403 rendering paths for build/ratify/action | logic tests (message maps) |
| Loading/empty for every panel; 401 redirect via client (regression) | api tests |
| Sensitive data: package payload renderer uses typed keys only (snapshot test of scheduleRows output keys) | `packageLogic.test.ts` |

## M. Manual browser smoke

- Prereqs/backend/frontend/seed: same as 08b1 §M; additionally a contract fixture that yields NEEDS_REVIEW (see `tests/extraction_fixtures.py` naming hints) and one that yields PASS.
- Backend command: as 08b1. Frontend: `npm run dev`.
- Actions & expectations:
  1. PASS transaction (both participants confirmed per PR 1 flow): `rules` shows comparison both sides + PASS findings; `ratification` shows policy panel (B1) — configure `document_only`, lock; build package → hash + schedule table (single milestone all_or_nothing on fake fixture); Berke ratifies (dialog shows hash) → "1/2"; Yusuf ratifies → `funding_triggered`, overview state `funding_pending`→`active` after refresh; events show `funding_required`/`funding_units_pool_created`.
  2. Both browsers compare `package_hash` strings — identical.
  3. NEEDS_REVIEW transaction: blocking validator case card; comment as manager works; resolve as normal user → 403 copy; (if a platform reviewer/admin seed exists) resolve_continue → state `preparation`; revision form (B2): edit a rule %, submit → new version in list, revalidate, diff shows the change.
  4. Ratify replay: click again → idempotent info, no error.
  5. Rule revision after ratification attempt → 409 Turkish copy.
- Failure checks: kill backend mid-build → network copy, no phantom package. Security: no `source_quote`/tax id in DOM; resolution_code input rejects lowercase (client hint) but backend remains authority. Responsive: schedule table horizontal-scrolls at 375 px; dialogs usable.

## N. Final verification commands

```bash
cd code/frontend
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
cd .. && ./.venv/bin/python -m pytest tests/test_reviews_router.py tests/test_rule_revision_endpoints.py tests/test_ratification_package.py tests/test_ratifications.py -q
git diff --check
git status --short
```

## O. Expected file manifest

Created: `src/types/{reviews,rules,ratification,tracking}.ts` · `src/api/{reviews,rules,ratification,tracking}.ts` + `src/api/{reviews,ratification}.test.ts` · `pages/transactions/TransactionRulesPage.tsx` · `pages/transactions/rules/{PartyComparisonPanel,ValidatorFindingsPanel,ReviewCasesPanel,RuleVersionsPanel}.tsx` + `{rulesLogic,ruleDiff,revisionForm}.ts` + tests · `pages/transactions/TransactionRatificationPage.tsx` · `pages/transactions/ratification/{PolicyPanel,PackagePanel,RatifyPanel}.tsx` + `{policyLogic,packageLogic}.ts` + tests.
Modified: `components/TransactionShell.tsx`, `routes/AppRoutes.tsx`, `pages/index.ts`, `lib/statusMaps.ts` (+test), `lib/eventLabels.ts`, `code/frontend/README.md`, `ARCHITECTURE.md` (route list), this plan.
Uncertainty: `api/tracking.ts` + `types/tracking.ts` + B2 read function shapes depend on the blocker-resolving backend contracts — cannot be eliminated until B1/B2 land; everything else is fixed.

## P. Binary acceptance criteria

1. Frontend CI commands all exit 0; backend targeted tests unchanged-green; no backend file diffs.
2. `rules` and `ratification` sections render for a PR 1-created transaction without console errors.
3. Both parties see byte-identical `package_hash` (smoke evidence).
4. Ratify replay returns success-idempotent UI (no error) — test + smoke.
5. Every 409 code in §C tables has a mapped Turkish message or raw-code fallback (tests).
6. `funding_triggered` unknown/false replay never rendered as failure (test).
7. No client-side computation of hash/schedule/readiness (code review check: `packageLogic.ts` contains no hashing/summing beyond display flattening).
8. Policy lock (B1) and rule revision (B2) demonstrated in smoke — REQUIRED before merge; if impossible the PR stays draft/BLOCKED.
9. No new npm dependency.

## Q. Implementation handoff prompt

```
You are implementing frontend PR 2 of 3 for M4Trust. Repository: gencberke/M4Trust-B2B-deal-management. Base: the branch that already contains BOTH commit ebf6dc7 (PR #67) and the merged feat/frontend-deal-core PR (program/domain-evolution-v2, or master if it has caught up).
1. Read AGENTS.md, plans/ready/08_frontend_completion_master_plan.md, plans/ready/08b2_frontend_rules_ratification.md fully.
2. Run §B preflight. Item 1 is a hard gate: if the account tracking-policy endpoints (B1) or the rule-set version read (B2) do not exist in the backend, STOP and report BLOCKED — do not invent routes, do not use manager_token endpoints, do not write raw SQL.
3. If the gate passes, record the two new contracts into §C-TP / §C-RS0 wording of your working notes, create branch feat/frontend-rules-ratification from the verified base.
4. Execute §K Tasks 1→7 in order (Tasks 4 and 6 use the preflight-recorded contracts); tests with every packet; Turkish UI strings.
5. Never modify backend files, api/client.ts, contexts, PR 1 components' props/context shape.
6. Exactly the 3 commits in §A. Run all §N commands green; git status --short must match §O.
7. Push, open a DRAFT PR against the verified base, body = scope + §P checklist + honest §M smoke report.
```

**Readiness status: `READY_TO_IMPLEMENT` (backend blockers resolved; frontend PR 1 base still required)**

Blockers (backend, not resolvable in frontend scope):
1. **B1** — no account_v2 tracking-policy configure/lock endpoints (legacy `manager_token` endpoints unusable for account rows; `ratification_package` fails closed with `TRACKING_POLICY_NOT_LOCKED`). Evidence: `routers/transactions.py:672-777`, `services/ratification_package.py:271-276`, `tests/test_ratification_package.py:83` (raw SQL lock in tests).
2. **B2** — no session read exposes current rule-set `version_id` / version history required by `POST .../rule-sets/{version_id}/revisions|validate` and the mandated version list/diff UI. Evidence: `routers/transactions.py:506-560` (detail projection), `routers/rule_sets.py` (no GET), `schemas/rule_sets.py`.

## R. Backend gap-closure update (2026-07-12)

The backend blockers B1, B2a, and B2b are resolved by `feat/backend-frontend-projection-gap-closure`. This file remains a ready frontend implementation plan; no frontend work is claimed complete here.

| Contract table entry | Implemented backend shape | Readiness |
|---|---|---|
| C-RS0 | `GET /api/transactions/{transaction_id}/rule-sets` returns `current_version_id`, `current_version`, and immutable `versions[]` for active assignments; projections omit `tax_id` and `source_quote` | READY |
| C3 revision body | Existing revision route now accepts dedicated `ExtractionRevisionRequest`; omitted `payment_rules[*].source_quote` values are merged from the current parent at the same rule index, then validated as frozen `ExtractionJSON` | READY |
| C-TP | `GET /api/transactions/{transaction_id}/tracking-policy`, `PUT` with `{physical_delivery_confirmed, tracking_mode}`, and `POST .../tracking-policy/lock` with empty body; session + CSRF + creator-manager + acting entity | READY |
| C6/C7 package progress | Current package projection includes `ratifications.buyer` and `.seller` with `ratified` and `approved_at` | READY |

The policy endpoints preserve the legacy capability compatibility body only for legacy callers; account_v2 callers must use the session/acting-entity branch. `source_quote` must never be filled with empty or masked text by the frontend.
