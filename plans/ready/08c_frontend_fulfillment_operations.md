# 08C — Frontend Slice C: Fulfillment and Operations (PR 3)

> **Durum:** Ready — 2026-07-12 · **Master:** `plans/ready/08_frontend_completion_master_plan.md` (§14.1 notes B3/B5 handled here as explicit UI limitations)
> **Readiness:** `READY_TO_IMPLEMENT` (see end of file; independent of PR 2's *implementation* — backend contracts for this slice are stable and the preflight detects drift; the PR still **merges after PR 2** per master §12)

## A. Phase identity

- **PR title:** `feat(frontend): Slice C — fulfillment, evidence, disputes and payment operations`
- **Branch:** `feat/frontend-fulfillment-operations`
- **Base:** the integration base per master plan §1 (`program/domain-evolution-v2`, or `master` once it contains `ebf6dc7`), **after PR 2 is merged into it**
- **Prerequisite merged PR:** PR 2 (`feat/frontend-rules-ratification`)
- **Included scope:** `fulfillment` section (milestone/funding-unit timeline projection, e-irsaliye + video evidence upload, evidence records + review status, evidence bundle view, immutable snapshot creation/view); `disputes` section (open, list, action timeline); `payments` section (reconcile, release retry, undo/refund request → bilateral approvals → execute, redacted provider/Moka trace, final settled/refunded/cancelled/blocked/recovery states); demo scenario support.
- **Excluded scope:** legacy delivery/evidence endpoints; platform-admin console; backend changes; polling of payment state.
- **Expected commits (exactly 3):**
  1. `feat(frontend): fulfillment — milestones, evidence upload, bundle and snapshots`
  2. `feat(frontend): disputes lifecycle`
  3. `feat(frontend): payment operations and redacted Moka trace` (+ doc-sync)

## B. Contract-drift preflight

1. `code/backend/app/routers/evidence_submit.py` — routes/fields/codes per §C1–C2 (`EIrsaliyeSubmitRequest` fields; video multipart `file` + `milestone_id` form field; 25 MB limit; `EVIDENCE_SUBMITTER_FORBIDDEN`, `EVIDENCE_SUBMISSION_STATE_INVALID`, `TRACKING_NOT_ENABLED`, `LEGACY_EVIDENCE_SUBMISSION_FORBIDDEN`, 413 `EVIDENCE_FILE_TOO_LARGE`, 422 `EVIDENCE_ANALYSIS_FAILED`, idempotency/milestone 409 codes from `services/evidence_records.py`).
2. `code/backend/app/routers/evidence.py` — `GET .../evidence-bundle`, `POST .../evidence-snapshots` responses per §C3–C4; bundle keys per `services/evidence.py::build_bundle_core`.
3. `code/backend/app/routers/disputes.py` — three routes; request/response models; action strings accepted by `services/disputes.py::record_dispute_action` (verify the exact action set — expected `comment`, `attach_evidence`, `escalate`, `resolve`, `cancel`; record the authoritative list from `services/disputes.py`).
4. `code/backend/app/routers/payment_ops.py` — six routes + trace per §C8–C13; `Idempotency-Key` header alternative on undo/refund; `_resolution_view` fields.
5. `code/backend/app/services/payments/payment_operations.py::get_payment_trace` — trace operation fields per §C13.
6. `code/backend/app/services/review.py` — `PAYMENT_RESOLUTION_CODES` and payment reason codes unchanged (`PAYMENT_POOL_CREATION_FAILED`, `PAYMENT_APPROVE_FAILED`, `PAYMENT_RECONCILE_AMBIGUOUS`, `PAYMENT_UNDO_REQUESTED`*, `PAYMENT_REFUND_REQUESTED`* — record exact constant values, `PAYMENT_UNDO_BLOCKED`, `PAYMENT_REFUND_FAILED`).
7. Frontend: PR 1 + PR 2 shared files present; shell registry `["overview","parties","rules","ratification"]`; `ReviewCasesPanel` exists and is reusable (payment cases render through it).
8. Re-verify B3/B5 gaps (release-instruction id and milestone id exposure): if the backend has since added `instruction_id`/`milestone_id`/funding-unit listings to reconcile results, trace, or a new read — **use them** and simplify §H accordingly (this is acceptable drift in the good direction; record it).

**Acceptable drift:** added fields, extra reason codes. **Stop:** removed/renamed routes; evidence submit no longer restricted to `active`; execute authorization model changed; trace no longer redacted-only fields.

## C. Verified contract table

### C1 `POST /api/transactions/{id}/evidence/e-irsaliye`
- Auth: session; active **manager** assignment or assignment representing the **seller participant**, with `X-Acting-Entity-ID` matching the assignment's entity. CSRF: yes.
- Request JSON: `{external_reference: string (1..128), delivered_quantity: number ≥0, milestone_id?: string|null}`.
- Response 200 `EvidenceRecordPublicView`: `{id, transaction_id, milestone_id, evidence_type: "e_irsaliye", source: "external_api", submitted_by_user_id, submitted_by_entity_id, external_reference, storage_ref: null, file_sha256: null, payload: {delivered_quantity}, verification_status: "verified", analyzer_provider: null, analyzer_version: null, created_at, verified_at}`.
- Preconditions: `account_v2`; state `active`; channel enabled (contractual e_irsaliye requirement OR locked policy mode `document_only|document_and_video`).
- Errors: 403 `EVIDENCE_SUBMITTER_FORBIDDEN` · 404 `TRANSACTION_NOT_FOUND` · 409 `LEGACY_EVIDENCE_SUBMISSION_FORBIDDEN`, `EVIDENCE_SUBMISSION_STATE_INVALID`, `TRACKING_NOT_ENABLED`, idempotency conflict codes (same `external_reference` different payload) and milestone codes (ambiguous candidates → explicit `milestone_id` required; wrong id → conflict) from `services/evidence_records.py` — render `error.code` + message.
- Idempotency: same `external_reference` replays the record (200) and re-triggers settlement — safe to repeat. **Side effects: may release funds** (settlement evaluation runs on success).
- Evidence: `routers/evidence_submit.py:186-215`, `tests/test_evidence_submit_api.py`.

### C2 `POST /api/transactions/{id}/evidence/video`
- Auth/CSRF/preconditions: as C1 but channel = video (contractual video OR policy `document_and_video`).
- Request `multipart/form-data`: `file` (≤ 25 MB), optional `milestone_id` form field.
- Response 200 `EvidenceRecordPublicView` with `evidence_type:"video"`, `source:"analyzer"`, `payload: {counts: Record<string,number>, unit_count: number, damage_signals: [{type, confidence, matched_box}], confidence: number}`, `verification_status: "verified"|"review_required"`, `file_sha256`, `analyzer_provider`, `analyzer_version`.
- Errors: as C1 plus 413 `EVIDENCE_FILE_TOO_LARGE`, 422 `EVIDENCE_ANALYSIS_FAILED`, 409 `EVIDENCE_IDEMPOTENCY_CONFLICT` (same file, different milestone).
- Idempotency: same file bytes (sha256) replay existing record. `review_required` opens a blocking settlement review (visible in rules section).
- Evidence: `routers/evidence_submit.py:248-351`.

### C3 `GET /api/transactions/{id}/evidence-bundle`
- Auth: session; any active assignment. CSRF: no. Side-effect free.
- Response 200: `{transaction: {id, state, created_at}|null, extraction: RedactedExtraction+source_quote-masked|null, validator_report, tracking_policy, approvals: [{party, created_at}], events: SafeEvent[], payments: MockPaymentRow[] (legacy table — usually empty for account), evidence_records: EvidenceRecordSummary[] ({id, evidence_type, source, verification_status, submitted_by_entity_id, submitted_by_role, external_reference, file_sha256, analyzer_provider, analyzer_version, created_at, verified_at, milestone_id}), ratification_package: {id, version, status, package_hash, created_at, opened_at, completed_at, ratifications: {buyer: {ratified, approved_at}, seller: {ratified, approved_at}}}|null, decision, snapshot_hash, generated_at}`.
- Errors: 401 · 403 `TRANSACTION_ACCESS_DENIED` · 404 `TRANSACTION_NOT_FOUND`. Evidence: `routers/evidence.py:63-72`, `services/evidence.py:263-322`, `tests/test_evidence_bundle.py`.
- **Note:** bundle `extraction` includes masked `source_quote` (authorized assignment-scoped view) — render quotes only inside the bundle viewer, nowhere else.

### C4 `POST /api/transactions/{id}/evidence-snapshots`
- Auth: session + assignment. CSRF: yes. Empty body.
- Response 200: `{snapshot_id, snapshot_hash, created: bool, bundle}` — `created:false` = idempotent replay of identical canonical core (render as success "Aynı snapshot zaten mevcut").
- Errors: 401/403/404 as C3. Evidence: `routers/evidence.py:75-119`, `tests/test_evidence_snapshot_api.py`.

### C5 `POST /api/transactions/{id}/disputes`
- Auth: session; **buyer/seller participant approver** (`role=approver` assignment bound to a buyer/seller participant, entity match via AE header). CSRF: yes.
- Request: `{milestone_id?: string|null, reason_code: string (1..64), description: string (1..2000)}`.
- Response 200 `DisputePublicView`: `{id, transaction_id, milestone_id, opened_by_user_id, opened_by_entity_id, reason_code, description, status, resolution_code, resolved_by_user_id, created_at, resolved_at}`.
- Errors: 400 `DISPUTE_CONTENT_REJECTED` (PII/token-like text) · 403 `DISPUTE_PARTICIPANT_APPROVER_REQUIRED` · 404 · 409 `LEGACY_DISPUTE_FORBIDDEN`, `DISPUTE_ALREADY_OPEN`.
- Side effect: open dispute blocks release (single release guard). Evidence: `routers/disputes.py:191-213`, `tests/test_disputes_api.py`.

### C6 `GET /api/transactions/{id}/disputes`
- Auth: session + assignment. Response 200: `DisputePublicView[]`. Errors: 403 `TRANSACTION_ACCESS_DENIED`. Evidence: `routers/disputes.py:216-226`.

### C7 `POST /api/disputes/{dispute_id}/actions`
- Auth: session. CSRF: yes. Request: `{action: string, comment?: ≤2000, resolution_code?: ≤64, evidence_id?: string|null, review_case_id?: string|null}`.
- Authorization: `resolve` → opener (same user+entity) or platform reviewer/admin; other actions → buyer/seller participant approver. Action set from `services/disputes.py` (preflight item 3).
- Response 200 `DisputeActionPublicView`: `{id, dispute_id, actor_user_id, acting_entity_id, action, evidence_id, payload, created_at}`.
- Errors: 400 `DISPUTE_CONTENT_REJECTED`, `DISPUTE_ACTION_INVALID` · 403 `DISPUTE_ACTION_FORBIDDEN`, `DISPUTE_RESOLVE_FORBIDDEN` · 404 `DISPUTE_NOT_FOUND` · 409 `DISPUTE_CLOSED`, `DISPUTE_CROSS_TRANSACTION_REFERENCE`.
- Side effect: `resolve`/`cancel` re-evaluate settlement. Evidence: `routers/disputes.py:229-274`.

### C8 `POST /api/transactions/{id}/payments/reconcile`
- Auth: session; **manager or platform reviewer/admin**. CSRF: yes. Empty body.
- Behavior: iterates funding units in `pool_creation_unknown|approval_unknown`, reconciles each against provider detail. Router calls no provider mutation — reconcile is read+state-bind; ambiguous drift opens blocking `PAYMENT_RECONCILE_AMBIGUOUS` review.
- Response 200: `{transaction_id, results: [{funding_unit_id, outcome, status, provider_status, retry_eligible: bool, review_opened: bool}]}` (empty results = nothing to reconcile — render info).
- Errors: 403 `PAYMENT_OPERATION_FORBIDDEN` · 404 `TRANSACTION_NOT_FOUND` · 409 `PAYMENT_RECONCILE_CONFLICT`.
- Retry-safe (reconcile-first design). Evidence: `routers/payment_ops.py:79-120`, `tests/test_payment_reconciliation.py`.

### C9 `POST /api/release-instructions/{instruction_id}/retry`
- Auth: manager or platform. CSRF: yes. Empty body. Precondition: instruction status ∈ `failed|unknown`; account_v2; reconciliation-first runs internally.
- Response 200: `{instruction_id, transaction_id, funding_unit_id, status: "confirmed"|"unknown"|"failed"|"unchanged", approved: bool, attempt_no: number|null}` — `unknown` is NOT failure (render "belirsiz — mutabakat gerekli").
- Errors: 403 `PAYMENT_OPERATION_FORBIDDEN` · 404 `RELEASE_INSTRUCTION_NOT_FOUND` · 409 `PAYMENT_RETRY_CONFLICT` (incl. ambiguous reconciliation, wrong status).
- **UI limitation (B3):** no read exposes `instruction_id`; the panel provides an operator input field (see §H) — documented limitation, revisit at preflight item 8.
- Side effects: provider approve attempt (financial). Same idempotency key reused backend-side. Evidence: `routers/payment_ops.py:123-145`, `services/payments/payment_operations.py:912-1005`.

### C10 `POST /api/funding-units/{funding_unit_id}/undo-request` · `.../refund-request`
- Auth: **transaction manager only** (platform NOT sufficient for request — verify in preflight; `request_resolution` enforces manager). CSRF: yes. Request: `{idempotency_key?: ≤128}` or `Idempotency-Key` header (UI: omit — backend derives deterministic key).
- Response 200 resolution view: `{id, transaction_id, funding_unit_id, review_case_id, operation_type: "undo_approval"|"refund", status: "requested"|"authorized"|"executing"|"executed"|"rejected"|"failed"|"unknown", idempotency_key, requested_by_user_id, requested_by_entity_id, executed_by_user_id, created_at, updated_at, approvals: [{participant_role, user_id, acting_entity_id, created_at}]}`.
- **No provider side effects**; opens blocking payment review case. Idempotent per unit+operation.
- Errors: 403 (manager check inside 409-wrapped `PAYMENT_RESOLUTION_CONFLICT`? — actual mapping: `PaymentOperationError` → 409 `PAYMENT_RESOLUTION_CONFLICT`; preflight confirms) · 404 (unit unknown → 409 message). `funding_unit_id` source: payment review case `source_id` (reuse from reviews data).
- Evidence: `routers/payment_ops.py:148-206`, `tests/test_payment_ops_api.py`.

### C11 `POST /api/payment-resolutions/{resolution_id}/approvals`
- Auth: buyer/seller participant approver (own side; same side cannot approve twice; same user cannot represent both). CSRF: yes. Empty body. Response 200: resolution view (approvals array grows).
- Errors: 403 `PAYMENT_RESOLUTION_APPROVAL_FORBIDDEN` (wraps all `PaymentOperationError`s here). Idempotent-ish per side.
- Evidence: `routers/payment_ops.py:209-222`.

### C12 `POST /api/payment-resolutions/{resolution_id}/execute`
- Auth: platform reviewer/admin OR bilateral (buyer+seller both approved) with executing actor associated to the transaction. CSRF: yes. Empty body.
- Response 200: `{resolution_id, funding_unit_id, operation_type, status, provider_outcome: string|null, provider_code: string|null}` — `status:"unknown"` = recoverable, NOT failure; repeat call reconciles.
- Errors: 409 `PAYMENT_RESOLUTION_EXECUTION_CONFLICT` (unauthorized, concurrent claim, refund unsupported → fail-closed review).
- **Provider side effects: yes** (undo/refund). ConfirmDialog with `requireText` (type the operation word). Evidence: `routers/payment_ops.py:225-245`, `services/payments/payment_operations.py` (BOLA/claim/unknown-reconcile semantics).

### C13 `GET /api/transactions/{id}/payment-trace`
- Auth: manager or platform. CSRF: no. Response 200: `{transaction_id, operations: [{operation_type, endpoint, timestamp, attempt_no, outcome, OtherTrxCode, VirtualPosOrderId, amount_minor, currency, idempotency_key, request_fingerprint, redacted_request: object, response: object|null, http_status, result_code, is_successful: bool|null, mapped_status}]}` — already redacted (no Password/CheckKey/CardToken/PAN/CVC/IP).
- Errors: 403 `PAYMENT_OPERATION_FORBIDDEN` · 404 · 409 `PAYMENT_TRACE_LEGACY_UNSUPPORTED`.
- Evidence: `routers/payment_ops.py:248-269`, `services/payments/payment_operations.py:834-877`.

## D. Blocking and non-blocking gaps

- **Blockers:** none (all mandated flows have contracts; two have documented UI limitations below).
- **Normalizable / documented limitations:**
  - **B3 (master §14.1):** `instruction_id` not discoverable → retry panel takes operator-pasted id; helper text explains where it comes from (backend logs/DB). Preflight item 8 upgrades this if the backend exposes it.
  - **B5:** milestone ids not enumerable → evidence forms leave `milestone_id` empty by default (single-candidate auto-bind); if the backend returns the ambiguity 409, show unsupported-state panel: "Bu işlemde birden çok milestone var; milestone kimliği API'de listelenmediği için kanıt şu an bağlanamıyor" + show any known ids from existing `evidence_records[].milestone_id` / dispute rows as suggestions.
  - Funding-unit ids come from payment review cases (`source_id`) and reconcile results — the payments panel lists "operable units" from those two sources only; it does not pretend to be a full unit ledger.
  - Milestone/funding-unit **timeline** is a projection: package `canonical_payload.funding_schedule` (structure) + events (`funding_required`, `funding_units_pool_created`, `funding_units_approved`, `transaction_settled`) + evidence records + payment cases. Live per-unit status is NOT available as a read; the timeline labels progress at transaction/event granularity and must say so ("birim bazlı canlı durum, mutabakat/inceleme kayıtlarından türetilir").
- **Unsupported states requiring clear UI:** refund on a gateway without refund support → execute 409 with fail-closed review (render backend message + "İade bu sağlayıcıda desteklenmiyor; inceleme açıldı"); `PAYMENT_RECONCILE_AMBIGUOUS` case → guidance to re-reconcile later.
- **Never assume:** never mark a unit released/refunded from a click result other than backend `status`; never treat `unknown` as failed **or** as success; never auto-repeat execute; never enable evidence upload from client-side policy interpretation (attempt → render 409 `TRACKING_NOT_ENABLED`).

## E. Route changes

- Created: `/transactions/:transactionId/fulfillment`, `/transactions/:transactionId/disputes`, `/transactions/:transactionId/payments` (shell children; RequireAuth inherited).
- Extended: shell registry → append `fulfillment`, `disputes`, `payments`; `statusMaps.ts` gains `evidenceStatusMap` (verified/review_required/rejected?), `disputeStatusMap`, `resolutionStatusMap`, `traceOutcomeMap`; `eventLabels.ts` verified for settlement labels.
- No redirects/guards/token changes. Section-local loading/failure per shared pattern.

## F. Exact TypeScript types

`src/types/evidence.ts`:
```ts
export interface DamageSignal { type: string; confidence: number; matched_box: boolean; }
export interface VideoEvidencePayload { counts: Record<string, number>; unit_count: number; damage_signals: DamageSignal[]; confidence: number; }
export interface EvidenceRecordPublicView { id: string; transaction_id: string; milestone_id: string | null; evidence_type: string; source: string; submitted_by_user_id: string; submitted_by_entity_id: string; external_reference: string | null; storage_ref: string | null; file_sha256: string | null; payload: Record<string, unknown>; verification_status: string; analyzer_provider: string | null; analyzer_version: string | null; created_at: string; verified_at: string | null; }
export interface EIrsaliyeSubmitRequest { external_reference: string; delivered_quantity: number; milestone_id?: string | null; }
export interface EvidenceRecordSummary { id: string; evidence_type: string | null; source: string | null; verification_status: string | null; submitted_by_entity_id: string | null; submitted_by_role: string | null; external_reference: string | null; file_sha256: string | null; analyzer_provider: string | null; analyzer_version: string | null; created_at: string | null; verified_at: string | null; milestone_id: string | null; }
export interface BundleRatificationSummary { ratified: boolean; approved_at: string | null; }
export interface BundlePackageView { id: string; version: number; status: string; package_hash: string; created_at: string; opened_at: string | null; completed_at: string | null; ratifications: { buyer: BundleRatificationSummary; seller: BundleRatificationSummary }; }
export interface EvidenceBundle { transaction: { id: string; state: string; created_at: string } | null; extraction: Record<string, unknown> | null; validator_report: { status: string | null; findings: unknown } | null; tracking_policy: Record<string, unknown> | null; approvals: { party: string; created_at: string }[]; events: { id: number; event_type: string; payload: Record<string, unknown> | null; source: string; created_at: string }[]; payments: unknown[]; evidence_records: EvidenceRecordSummary[]; ratification_package: BundlePackageView | null; decision: Record<string, unknown> | null; snapshot_hash: string; generated_at: string; }
export interface EvidenceSnapshotResponse { snapshot_id: string; snapshot_hash: string; created: boolean; bundle: EvidenceBundle; }
```

`src/types/disputes.ts`: `DisputeOpenRequest { milestone_id?: string|null; reason_code: string; description: string }`, `DisputePublicView` (per C5), `DisputeActionRequest { action: string; comment?: string; resolution_code?: string; evidence_id?: string|null; review_case_id?: string|null }`, `DisputeActionPublicView` (per C7).

`src/types/payments.ts`: `ReconcileUnitResult { funding_unit_id: string; outcome: string; status: string; provider_status: string|null; retry_eligible: boolean; review_opened: boolean }`, `ReconcileResponse { transaction_id: string; results: ReconcileUnitResult[] }`, `ReleaseRetryResponse { instruction_id: string; transaction_id: string; funding_unit_id: string; status: "confirmed"|"unknown"|"failed"|"unchanged" | (string & {}); approved: boolean; attempt_no: number|null }`, `ResolutionApproval { participant_role: string; user_id: string; acting_entity_id: string; created_at: string }`, `PaymentResolutionView { id: string; transaction_id: string; funding_unit_id: string; review_case_id: string|null; operation_type: "undo_approval"|"refund"; status: string; idempotency_key: string|null; requested_by_user_id: string; requested_by_entity_id: string; executed_by_user_id: string|null; created_at: string; updated_at: string; approvals: ResolutionApproval[] }`, `ResolutionExecuteResponse { resolution_id: string; funding_unit_id: string; operation_type: string; status: string; provider_outcome: string|null; provider_code: string|null }`, `PaymentTraceOperation` (all C13 fields, `redacted_request: Record<string, unknown>`, `response: Record<string, unknown>|null`), `PaymentTraceResponse { transaction_id: string; operations: PaymentTraceOperation[] }`.

`src/lib/milestoneProjection.ts` (pure): `buildMilestoneTimeline(pkg: RatificationPackagePublicView|null, events: TransactionEvent[], evidence: EvidenceRecordSummary[], paymentCases: ReviewCase[]): MilestoneTimelineRow[]` where `MilestoneTimelineRow { ruleIndex: number; title: string; releaseMode: string; amountMinor: number; currency: string; requiredEvidence: string[]; units: {sequence: number; amountMinor: number}[]; evidence: EvidenceRecordSummary[]; openPaymentCases: ReviewCase[]; transactionLevelEvents: {label: string; created_at: string}[] }` — matches evidence by `milestone_id` **only when non-null**; unmatched evidence goes to a "milestone'a bağlanmamış" bucket; no status guessing: unit progress text derives solely from event labels + case presence.

## G. Exact API functions

`src/api/evidence.ts`: `submitEIrsaliye(transactionId, body: EIrsaliyeSubmitRequest): Promise<EvidenceRecordPublicView>` POST csrf; `submitVideoEvidence(transactionId, form: FormData): Promise<EvidenceRecordPublicView>` POST csrf (FormData: `file`, optional `milestone_id`); `getEvidenceBundle(transactionId): Promise<EvidenceBundle>` GET `redirectOnError:false`; `createEvidenceSnapshot(transactionId): Promise<EvidenceSnapshotResponse>` POST csrf.

`src/api/disputes.ts`: `openDispute(transactionId, body)` POST csrf; `listDisputes(transactionId)` GET; `submitDisputeAction(disputeId, body)` POST csrf.

`src/api/payments.ts`: `reconcilePayments(transactionId)` POST csrf; `retryReleaseInstruction(instructionId)` POST csrf; `requestUndo(fundingUnitId)` / `requestRefund(fundingUnitId)` POST csrf body `{}`; `approveResolution(resolutionId)` POST csrf; `executeResolution(resolutionId)` POST csrf; `getPaymentTrace(transactionId)` GET `redirectOnError:false` (403 renders in-panel "Yalnız işlem yöneticisi ve platform görevlileri").

All mutations `redirectOnError:false`.

## H. Page and component tree

| File | Component | Spec |
|---|---|---|
| `pages/transactions/TransactionFulfillmentPage.tsx` | `TransactionFulfillmentPage` | Reads (parallel): bundle (`getEvidenceBundle`), current package (`getCurrentRatificationPackage`, reuse PR 2 api), reviews (`listReviews`, reuse), shell detail (context). Blocks: MilestoneTimelinePanel, EvidenceUploadPanel, EvidenceRecordsPanel, BundlePanel. |
| `pages/transactions/fulfillment/MilestoneTimelinePanel.tsx` | `MilestoneTimelinePanel` | Props: `rows: MilestoneTimelineRow[]`, `state`. Renders per-milestone card: title, amount, release mode badge, required evidence chips, unit table (sequence/amount), linked evidence list, open payment cases, transaction-level funding events `Timeline`. Projection disclaimer text per §D. Empty (no package) → "Onay paketi oluşturulmadan milestone planı yoktur". |
| `pages/transactions/fulfillment/EvidenceUploadPanel.tsx` | `EvidenceUploadPanel` | Two `CommandPanel`s. E-irsaliye: external_reference, delivered_quantity (number ≥0), optional milestone_id text input (helper per B5); ConfirmDialog ("Kanıt gönderimi ödeme değerlendirmesini tetikleyebilir"); success → refresh bundle+reviews+shell + Notice incl. `verification_status`. Video: file input (accept video/*, image/* per analyzer; ≤25 MB client pre-check), optional milestone_id; progress disabled-state while uploading; success renders payload summary (unit_count, damage signal count, confidence) + `review_required` warning Notice when applicable. Error map per C1/C2 codes incl. 413/422 and ambiguity per §D-B5. Panel disabled with reason when `state !== "active"` (text from backend 409 after attempt as authority; pre-disable is cosmetic only). |
| `pages/transactions/fulfillment/EvidenceRecordsPanel.tsx` | `EvidenceRecordsPanel` | `ResponsiveTable` of `bundle.evidence_records`: type, status badge, external_reference/sha short, milestone_id, submitted_by_role, created_at. |
| `pages/transactions/fulfillment/BundlePanel.tsx` | `BundlePanel` | Shows `snapshot_hash` (monospace + copy), `generated_at`, package ratification summary (buyer/seller ratified badges), decision block (safe keys: action, capture_ratio, manual_review_required, findings codes), collapsible `<details>` sections rendering typed sub-views (never raw JSON dumps except events payloads already sanitized backend-side, shown in a `<pre>` inside `overflow-x-auto`). Snapshot button (ConfirmDialog) → `createEvidenceSnapshot`; result Notice "Snapshot oluşturuldu/zaten mevcut (hash …)". |
| `pages/transactions/TransactionDisputesPage.tsx` | `TransactionDisputesPage` | Read: `listDisputes`. Open-dispute `CommandPanel`: reason_code input (A-Z0-9_ hint), description textarea, optional milestone_id; ConfirmDialog ("İtiraz ilgili ödemeleri bloklar"); errors per C5 map. Dispute cards: status badge, reason, description, opened_by entity short, resolution fields; per-dispute action panel (action select from preflight-recorded set, comment, resolution_code for resolve, optional evidence_id select from bundle evidence records); errors per C7; `resolve`/`cancel` success → refresh disputes+reviews+shell. |
| `pages/transactions/TransactionPaymentsPage.tsx` | `TransactionPaymentsPage` | Reads (parallel): `getPaymentTrace` (403-tolerant), `listReviews` (payment-phase cases), shell context. Blocks: ReconcilePanel, OperableUnitsPanel, RetryPanel, TracePanel. |
| `pages/transactions/payments/ReconcilePanel.tsx` | `ReconcilePanel` | Button + ConfirmDialog; result table of `ReconcileUnitResult` (outcome/status/provider_status/retry_eligible/review_opened badges); empty results info; refresh trace+reviews+shell on success. |
| `pages/transactions/payments/OperableUnitsPanel.tsx` | `OperableUnitsPanel` | Derives operable funding units from payment review cases (`source_id`) + last reconcile results (page state). Per unit: reason_code badges, then commands: "Geri alma talebi" / "İade talebi" (manager; ConfirmDialog; → resolution view card), resolution card shows status + approvals (buyer/seller check marks) + "Onayla (taraf)" button (`approveResolution`) + "Uygula" button (`executeResolution`, ConfirmDialog `requireText` = operation word, danger tone); execute result per C12 incl. `unknown` copy "belirsiz — mutabakat gerekli, tekrar 'Uygula' güvenlidir"; all errors inline per code maps. |
| `pages/transactions/payments/ReleaseRetryPanel.tsx` | `ReleaseRetryPanel` | Operator input `instruction_id` (B3 limitation text), retry button + ConfirmDialog; result per `ReleaseRetryResponse` (`confirmed`→success; `unknown`→ambiguous copy; `failed`→danger + "inceleme açık olabilir"); refresh trace+reviews+shell. |
| `pages/transactions/payments/TracePanel.tsx` | `TracePanel` | Badge "public contract simulation"; `ResponsiveTable`: type, endpoint, attempt_no, outcome badge, OtherTrxCode, amount (`formatAmountMinor`), timestamp; row expander showing `redacted_request`/`response` in `<pre>` (JSON.stringify of the typed fields, backend-redacted) inside `overflow-x-auto`; 403 → permission Notice; 409 legacy → info. |

Loading/empty/error/permission/conflict/responsive/a11y: shared patterns; every financial button disabled while busy; unknown outcomes never red.

## I. Data loading and mutation refresh

| Page | Initial reads | Order | Mutation → refresh |
|---|---|---|---|
| Fulfillment | bundle ∥ package ∥ reviews | parallel | evidence submit → bundle+reviews+shell; snapshot → none (renders response) + manual bundle refresh button |
| Disputes | disputes | single | open/action → disputes; resolve/cancel additionally reviews+shell |
| Payments | trace ∥ reviews | parallel | reconcile/retry/execute → trace+reviews+shell; request/approve → local resolution card + reviews |

No polling (master §8); every panel has manual "Yenile". Failures inline; 409 → message + refresh CTA; cancellation via `useAsyncData` guard; stale resolution card superseded by refreshed reviews on conflict.

## J. Lifecycle and action matrix

| State | Fulfillment | Disputes | Payments |
|---|---|---|---|
| pre-`active` (preparation…funding_pending) | timeline from package if built; upload disabled reason "İşlem aktif değil" (backend 409 authority) | open allowed? backend: dispute open not state-gated beyond account_v2 — allow attempt, render result | reconcile available when unknown units exist (funding_pending!); trace visible to manager; resolutions n/a until units exist |
| `active` | upload enabled per channel; records grow; review_required video → blocking case | open/action full | reconcile/retry/resolutions as cases appear |
| `settled` | uploads → 409 state invalid (rendered); bundle/snapshot fully available | actions on open disputes still possible (resolve) | trace read-only; undo/refund requests may still 409/flow per backend — render results |
| `rejected`/`cancelled` | read-only bundle | list read-only (open likely 409/403 — render) | trace if manager |
| blocked (open blocking review/dispute) | uploads accepted but release held — Notice explains hold from open cases | — | execute/retry gated by backend preconditions |

Backend-owned, never derived: release eligibility, cumulative delivered quantity, decision outcomes, resolution authorization, provider status.

## K. Execution task packets

#### Task 1 — Evidence types + API
**Goal** typed evidence layer.
**Depends on** PR 2 merged.
**Files to create** `src/types/evidence.ts`, `src/api/evidence.ts`, `src/api/evidence.test.ts`
**Files to modify** `src/lib/statusMaps.ts` (`evidenceStatusMap`), test
**Required changes** §F/§G/C1–C4; video via FormData without manual Content-Type.
**Must not change** client, PR1/PR2 modules.
**Tests** parse fixtures for both record types + bundle; 413/422/409 code passthrough; snapshot `created:false` handling helper.
**Verification commands** `cd code/frontend && npm run lint && npm run typecheck && npm run test`
**Done when** green.

#### Task 2 — Milestone projection lib
**Goal** pure timeline projection.
**Depends on** Task 1
**Files to create** `src/lib/milestoneProjection.ts`, `src/lib/milestoneProjection.test.ts`
**Required changes** per §F signature; no status inference beyond event labels/case presence; unmatched-evidence bucket.
**Tests** package+events+evidence fixtures: correct grouping; null-milestone evidence bucketed; no unit marked "approved" without the corresponding event/case data (assert output contains no such field at all).
**Done when** green.

#### Task 3 — Fulfillment section pages
**Goal** `/fulfillment` live.
**Depends on** Tasks 1–2
**Files to create** `pages/transactions/TransactionFulfillmentPage.tsx`, `pages/transactions/fulfillment/{MilestoneTimelinePanel,EvidenceUploadPanel,EvidenceRecordsPanel,BundlePanel}.tsx`, `pages/transactions/fulfillment/fulfillmentLogic.ts` + test
**Files to modify** shell registry, `routes/AppRoutes.tsx`, `pages/index.ts`
**Required changes** §H rows 1–5; `fulfillmentLogic.ts`: `evidenceErrorMessage(code, status)`, `videoPayloadSummary(payload)`, `clientFileTooLarge(file)` (25 MB).
**Tests** error map incl. 413/422/ambiguity; payload summary; size check boundary.
**Done when** green; e-irsaliye submit works against an `active` dev transaction.

#### Task 4 — Disputes types + API + section
**Goal** `/disputes` live.
**Depends on** Task 1 (bundle evidence ids for attach)
**Files to create** `src/types/disputes.ts`, `src/api/disputes.ts`, `src/api/disputes.test.ts`, `pages/transactions/TransactionDisputesPage.tsx`, `pages/transactions/disputes/disputesLogic.ts` + test
**Files to modify** shell registry, routes, `pages/index.ts`, `statusMaps.ts` (`disputeStatusMap`)
**Required changes** §C5–C7/§H row 6; `disputesLogic.ts`: action set constant (from preflight), `disputeErrorMessage(code)`.
**Tests** api parse; error maps (400 content-rejected, 403 both codes, 409 closed/already-open/cross-ref); action payload allowlist.
**Done when** green; open→comment→resolve flow works in dev.

#### Task 5 — Payments types + API
**Goal** typed payment-ops layer.
**Depends on** —
**Files to create** `src/types/payments.ts`, `src/api/payments.ts`, `src/api/payments.test.ts`
**Files to modify** `statusMaps.ts` (`resolutionStatusMap`, `traceOutcomeMap`) + test
**Required changes** §F/§G/C8–C13.
**Tests** reconcile/retry/resolution/execute/trace parsing; `unknown` status mapping to warning (never danger); 403/404/409 passthrough.
**Done when** green.

#### Task 6 — Payments section pages
**Goal** `/payments` live.
**Depends on** Tasks 4–5 (reviews reuse)
**Files to create** `pages/transactions/TransactionPaymentsPage.tsx`, `pages/transactions/payments/{ReconcilePanel,OperableUnitsPanel,ReleaseRetryPanel,TracePanel}.tsx`, `pages/transactions/payments/paymentsLogic.ts` + test
**Files to modify** shell registry, routes, `pages/index.ts`
**Required changes** §H rows 7–11; `paymentsLogic.ts`: `operableUnitsFromCases(cases)` (payment-phase, source_id non-null, dedupe), `mergeReconcileResults(units, results)`, `executeConfirmWord(operationType)` ("GERI-AL"/"IADE"), `paymentErrorMessage(code)`, `outcomeTone(status)` (unknown→warning).
**Tests** unit derivation/dedup; outcome tones (unknown ≠ danger); confirm word; error maps.
**Done when** green; reconcile + trace render against a mock-Moka funded dev transaction.

#### Task 7 — Demo scenario support + docs + doc-sync
**Goal** README demo guide + route doc-sync; final pass.
**Depends on** Tasks 1–6
**Files to modify** `code/frontend/README.md` (add "Demo senaryosu" section: seed, fixture names incl. fault tokens `DEMO-TOKEN-TIMEOUT-AFTER-CREATE`, mock-Moka two-terminal topology, the master §13 click-path), `ARCHITECTURE.md` (frontend route list line), this plan status block.
**Must not change** other ARCHITECTURE sections.
**Verification commands** §N.
**Done when** §N green; manifest = §O.

## L. Test matrix

| Scenario | Where |
|---|---|
| Evidence submit success (both types), idempotent replay (same reference/file → 200 existing) | `api/evidence.test.ts` |
| 403 `EVIDENCE_SUBMITTER_FORBIDDEN`; 409 state/tracking/idempotency/milestone codes; 413; 422 analysis | `fulfillmentLogic.test.ts` |
| Bundle parse incl. null package/extraction; snapshot created true/false | `api/evidence.test.ts` |
| Milestone projection grouping + null-milestone bucket + no invented statuses | `milestoneProjection.test.ts` |
| Dispute open/action codes (400/403/404/409 full set) | `disputesLogic.test.ts`, `api/disputes.test.ts` |
| Reconcile parse; empty results; 409 conflict | `api/payments.test.ts` |
| Retry statuses incl. `unknown` → warning tone, `unchanged` copy | `paymentsLogic.test.ts` |
| Resolution lifecycle: request idempotent, approvals accumulate, execute unknown-recoverable copy, `PAYMENT_RESOLUTION_EXECUTION_CONFLICT` | `api/payments.test.ts`, `paymentsLogic.test.ts` |
| Financial unknown states never rendered as definitive failure (tone tests) | `paymentsLogic.test.ts` |
| Trace parse; redacted fields only (type-level: renderer consumes typed keys; test asserts renderer helper output keys ⊆ C13 field list) | `api/payments.test.ts` |
| 401 anywhere → session kind (regression), 403 trace → in-panel mode | api tests |
| Network failure on execute → "durumu yenileyin" copy, no auto-retry | `paymentsLogic.test.ts` |
| Invalid response envelope → generic | api tests |
| Loading/empty for each panel; authorization-dependent visibility via error rendering | logic tests |
| Sensitive data: bundle renderer never outputs `storage_ref` (helper filter test) | `fulfillmentLogic.test.ts` |

## M. Manual browser smoke

- **Prereqs:** as 08b1 §M plus: Terminal A `cd code && ./.venv/bin/uvicorn backend.mock_moka.app:app --port 8001`; `code/.env`: `PAYMENT_PROVIDER=moka_http`, `MOKA_BASE_URL=http://127.0.0.1:8001`, mock demo credentials from `backend/.env.example`, `VIDEO_PROVIDER=fake` (or keep `PAYMENT_PROVIDER=fake` for a no-mock run — state which was used). A transaction driven through PR 1+2 flows to `active` (policy lock via B1 endpoints).
- **Frontend:** `npm run dev`.
- **Actions & expectations:**
  1. `fulfillment`: milestone card(s) from package schedule; disclaimer text present. Submit e-irsaliye (full quantity) as Yusuf(seller) → verified record; events gain `funding_units_approved`; state → `settled` on refresh (single-milestone fixture); `transaction_settled` in timeline.
  2. Video with `hasarli`-named file on a second active transaction → `review_required` record + blocking settlement case visible under `rules`; release held; resolve with `VIDEO_FALSE_POSITIVE` (platform seed) → subsequent evidence releases.
  3. Same video file re-upload → idempotent (same record id), no duplicate.
  4. `disputes`: as Berke(buyer approver) open dispute → release blocked; comment from Yusuf; resolve as opener → settlement re-evaluates.
  5. Bundle: snapshot → hash; snapshot again → "zaten mevcut", same hash; no `storage_ref`/token strings in DOM (devtools search).
  6. `payments` (fault run): fund a transaction using mock-Moka fault token flow (`DEMO-TOKEN-TIMEOUT-AFTER-CREATE` per `tests/test_moka_multi_release_e2e.py` / mock docs) → unit `pool_creation_unknown`; reconcile button → results table binds status; review case list updates.
  7. Undo-request on an approved unit (manager) → resolution card `requested` + blocking case; approve as buyer, approve as seller → `authorized`... execute (typed confirm) → status per provider; `unknown` path shows ambiguous copy and repeat-execute reconciles.
  8. Trace panel: operations with attempt_no/outcome; expanders show redacted JSON; "public contract simulation" badge; no Password/CheckKey anywhere.
  9. Retry panel: paste an instruction id (from backend DB/log) with `failed|unknown` instruction → result rendered per status; garbage id → 404 copy.
- **Failure checks:** backend down mid-execute → network copy, no state change claimed. **Security checks:** as listed + evidence upload >25 MB blocked client-side with Turkish message. **Responsive:** trace/table horizontal scroll at 375 px; dialogs with `requireText` usable on mobile keyboard.

## N. Final verification commands

```bash
cd code/frontend
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
cd .. && ./.venv/bin/python -m pytest tests/test_evidence_submit_api.py tests/test_evidence_bundle.py tests/test_evidence_snapshot_api.py tests/test_disputes_api.py tests/test_payment_ops_api.py tests/test_payment_operations.py tests/test_payment_reconciliation.py -q
git diff --check
git status --short
```

## O. Expected file manifest

Created: `src/types/{evidence,disputes,payments}.ts` · `src/api/{evidence,disputes,payments}.ts` + three api tests · `src/lib/milestoneProjection.ts` + test · `pages/transactions/TransactionFulfillmentPage.tsx` + `fulfillment/{MilestoneTimelinePanel,EvidenceUploadPanel,EvidenceRecordsPanel,BundlePanel}.tsx` + `fulfillmentLogic.ts` + test · `pages/transactions/TransactionDisputesPage.tsx` + `disputes/disputesLogic.ts` + test · `pages/transactions/TransactionPaymentsPage.tsx` + `payments/{ReconcilePanel,OperableUnitsPanel,ReleaseRetryPanel,TracePanel}.tsx` + `paymentsLogic.ts` + test.
Modified: `components/TransactionShell.tsx` (registry), `routes/AppRoutes.tsx`, `pages/index.ts`, `lib/statusMaps.ts` (+test), `lib/eventLabels.ts`, `code/frontend/README.md`, `ARCHITECTURE.md` (route list), this plan.
Uncertainty: exact dispute action set + evidence idempotency/milestone 409 code strings are read from `services/disputes.py`/`services/evidence_records.py` during preflight (they exist; only the literal strings are confirmed then). If preflight item 8 finds new id-exposing fields, `OperableUnitsPanel`/`ReleaseRetryPanel` simplify — noted as the only structural variance.

## P. Binary acceptance criteria

1. Frontend CI commands exit 0; targeted backend tests green; zero backend diffs.
2. Sections `fulfillment`, `disputes`, `payments` render for an `active` account transaction without console errors.
3. E-irsaliye submit on the demo fixture drives the transaction to `settled` (smoke evidence).
4. Video `review_required` path produces a visible blocking case and held release (smoke).
5. Snapshot idempotency demonstrated (same hash, `created:false`) — test + smoke.
6. Every §C error code has mapped copy or raw-code fallback (tests).
7. `unknown` payment outcomes render as warning/ambiguous in all panels — tone tests pass; no code path maps unknown→danger.
8. Execute requires typed confirmation; no financial mutation auto-retries (code check: no retry loops in `api/payments.ts`/panels).
9. Trace panel renders only C13 fields; DOM contains no Password/CheckKey/CardToken strings (smoke devtools search).
10. No new npm dependency.

## Q. Implementation handoff prompt

```
You are implementing frontend PR 3 of 3 for M4Trust. Repository: gencberke/M4Trust-B2B-deal-management. Base: the branch that already contains the merged feat/frontend-rules-ratification PR (program/domain-evolution-v2, or master if it has caught up).
1. Read AGENTS.md, plans/ready/08_frontend_completion_master_plan.md, plans/ready/08c_frontend_fulfillment_operations.md fully.
2. Run §B preflight (named files only). Record the literal dispute action set and evidence 409 code strings; check preflight item 8 for newly exposed instruction/milestone ids. On any "stop" condition, STOP and report drift.
3. Create branch feat/frontend-fulfillment-operations from the verified base.
4. Execute §K Tasks 1→7 in order; tests with every packet; Turkish UI strings; unknown payment outcomes are NEVER rendered as failure.
5. Never modify backend files, api/client.ts, contexts, or PR 1/PR 2 component props/context shapes.
6. Exactly the 3 commits in §A. Run all §N commands green; git status --short must match §O.
7. Push, open a DRAFT PR against the verified base, body = scope + §P checklist + honest §M smoke report (say explicitly which provider mode was used and which steps were not run).
```

**Readiness status: `READY_TO_IMPLEMENT`**

(Sequencing note: merges after PR 2. Backend contracts consumed here are stable at HEAD `ebf6dc7`; dependency assumptions on PR 1/PR 2 shared components are explicit in §B item 7; the preflight detects relevant drift. Documented limitations B3/B5 are unsupported-state UI, not blockers. The *end-to-end demo* additionally requires PR 2's blockers B1/B2 to be resolved so a transaction can reach `active` through the browser.)

## R. Backend gap-closure update (2026-07-12)

The backend projection gaps B3, B5, B6, and B7 are resolved by `feat/backend-frontend-projection-gap-closure`. This file remains a ready frontend implementation plan; no frontend work is claimed complete here.

| Fulfillment/operations contract | Implemented backend shape | Readiness |
|---|---|---|
| Milestone and funding-unit projection | `GET /api/transactions/{transaction_id}/milestones` returns current-package milestones with real IDs, `rule_index`, status, amounts, required evidence, nested funding units, unit sequence/status, milestone mapping, and nullable release-instruction ID/status | READY |
| Payment resolution list | `GET /api/transactions/{transaction_id}/payment-resolutions` returns assignment-scoped resolution views with approvals | READY |
| Payment resolution detail | `GET /api/transactions/{transaction_id}/payment-resolutions/{resolution_id}` returns the same safe projection; cross-transaction IDs are opaque 404s | READY |
| B3/B5/B6/B7 limitations in §D | Replaced by the reads above; frontend may enumerate milestone choices, healthy funding units, release instructions, and bilateral resolution IDs | RESOLVED |

The projection does not expose provider credentials, raw payloads, storage paths, tokens, or secrets. Account/session bundle and snapshot reads also omit `source_quote`.
