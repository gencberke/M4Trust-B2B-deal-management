# 08 — Frontend Completion Master Plan (Program 6, Phases 8B1 / 8B2 / 8C)

> **Durum:** Ready — 2026-07-12 · **Master ref:** v2 §2.13, Program 6 · `plans/ready/08_frontend_vertical_slices.md` (superseded slicing: 5 slices → 3 PRs, bkz. §12)
> **Scope:** Shared architecture for the three remaining frontend PRs. Child execution plans:
> `08b1_frontend_deal_core.md` · `08b2_frontend_rules_ratification.md` · `08c_frontend_fulfillment_operations.md`
> **Language note:** planning text is English for implementation-model determinism; **all user-facing UI strings must be Turkish** (AGENTS.md binding rule). Existing Turkish strings in `code/frontend/src` show the expected tone.

---

## 1. Verified baseline

Verified on branch `program/domain-evolution-v2`, HEAD `ebf6dc7a4ee8c6589329a514368d8e53f6f35ce9` (= merge of PR #67 `feat/frontend-foundation`). **Base-branch reality check (verified 2026-07-12):** `origin/master` is at `69e5f9a` and does **not** yet contain PR #67 — the frontend foundation exists only on `program/domain-evolution-v2` (3 commits ahead). Child PRs therefore branch from and target **`program/domain-evolution-v2`** unless a program→master merge has landed by implementation time, in which case `master` may be used. Every child preflight verifies the chosen base contains commit `ebf6dc7` (`git merge-base --is-ancestor ebf6dc7 <base>`).

### 1.1 Merged frontend foundation (Phase 8A, PR #67)

`code/frontend/` — React 19 + Vite 7 + TypeScript 5.9 + Tailwind 4 + react-router-dom 7 + vitest 4. npm, `packageManager: npm@10.9.2`, Node 22.

```
code/frontend/src/
├── api/client.ts            # central API client (frozen behavior; extend, never replace)
├── api/client.test.ts
├── auth/AuthContext.tsx      # AuthProvider/useAuth; /auth/me bootstrap; login/register/logout
├── entities/EntityContext.tsx # EntityProvider/useEntities; GET /entities; selected entity →
│                              #   setApiActingEntityId + localStorage "m4t_acting_entity_id"
├── components/AppShell.tsx    # header, nav, acting-entity <select>, <Outlet/>
├── components/Feedback.tsx    # PageHeading · Notice(info/success/warning/danger) · LoadingPanel · RetryPanel
├── pages/{HomePage,AuthPages,EntityPages,ErrorPages,shared,index}.tsx
├── routes/AppRoutes.tsx       # route table + RequireAuth + ApiErrorRedirector
├── routes/navigation.ts       # ApiErrorNavigationState helpers
├── types/api.ts               # ApiErrorEnvelope/ApiErrorKind/UserPublic/EntityPublic + requests
├── index.css · main.tsx
```

### 1.2 Existing route map (must be preserved)

| Route | Page | Guard |
|---|---|---|
| `/` | HomePage | — |
| `/register`, `/login` | AuthPages | — |
| `/logout`, `/me` | AuthPages | RequireAuth |
| `/entities/new`, `/entities/:entityId` | EntityPages | RequireAuth |
| `/session-required`, `/permission-denied`, `/conflict` | ErrorPages | — |
| `*` | NotFoundPage | — |

### 1.3 API-client behavior (`src/api/client.ts`) — frozen contract

- `apiRequest<T>(path, options)` prefixes `/api`, always `credentials: "include"`.
- JSON body auto-serialized; `FormData`/`Blob`/`URLSearchParams`/string passed through (multipart Content-Type left to the browser).
- `options.csrf: true` → reads cookie `m4t_csrf`, sends `X-CSRF-Token`; missing cookie throws `ApiClientError(kind="permission_denied", code="CSRF_COOKIE_MISSING")` without hitting the network.
- Acting entity: module-level `setApiActingEntityId(id)` → `X-Acting-Entity-ID` header on every request (owned by `EntityContext`).
- Error mapping: HTTP status → `ApiErrorKind` (`401 session_required · 403 permission_denied · 404 not_found · 409 conflict · 422 validation · ≥500 server`); parses the standard envelope `{code, message, request_id, detail?}` when present, otherwise generic Turkish messages. Non-JSON error bodies never surface raw.
- `redirectOnError` (default `true`) routes 401/403/409 to `/session-required` / `/permission-denied` / `/conflict` via `setApiNavigationErrorHandler`. Page-local error handling passes `redirectOnError: false`.

**Important nuance for all child plans:** several backend endpoints raise plain `HTTPException` with a *string* `detail` (legacy-era contracts, e.g. `GET /api/transactions/{id}` 401/403/404, upload 400, policy 409 with `PolicyConflict` object detail). The client tolerates these: `parseApiErrorEnvelope` fails → generic message by status, `code = HTTP_<status>`. Child plans must branch on `error.status`/`error.kind` first and on `error.code` only for endpoints that use the `ApiError` envelope; never display `error.detail` raw.

### 1.4 Auth & entity state ownership

- `AuthContext` owns `user: UserPublic | null` (bootstrap `GET /auth/me`, 401 ⇒ anonymous). Preserve as-is.
- `EntityContext` owns entity list + selected acting entity; persists only the non-sensitive entity **id** in localStorage; syncs the API-client header. Preserve as-is.
- No auth token ever in localStorage/sessionStorage.

### 1.5 UI primitives, tests, CI

- Primitives: `PageHeading`, `Notice`, `LoadingPanel`, `RetryPanel`, `pages/shared.tsx` (`inputClass`, `buttonClass`, `secondaryButtonClass`, `FormError`, `Info`, `parseAddress`).
- Tests: 8A ships vitest node environment, `src/**/*.test.ts` only (pure helpers — `client.test.ts`, `AuthContext.test.ts`, `EntityContext.test.ts`, `navigation.test.ts`). **This program extends the strategy in PR 1:** pure-helper tests remain the default for logic, and a small DOM layer is added for behavior that helpers cannot cover (dialog focus trap, route guards/nesting, disabled states, async render). PR 1 adds dev-only dependencies `jsdom`, `@testing-library/react`, `@testing-library/user-event` and a `src/**/*.test.tsx` include with `environment: "jsdom"` per-file (`// @vitest-environment jsdom`) so existing node tests are untouched. No new *runtime* dependency is permitted in any PR.
- CI: `.github/workflows/frontend-ci.yml` — `npm ci`, `lint`, `typecheck`, `test`, `build` on Node 22, working dir `code/frontend`. Backend CI is separate (`backend-ci.yml`); frontend PRs must not touch it.

### 1.6 Repository ownership rules

`code/frontend/**` (incl. `vite.config.ts`) is frontend-owned; backend files, tests under `code/tests`, `AGENTS.md`, `ARCHITECTURE.md` §4 contracts are **not modified** by these PRs. Doc-sync at each PR close: ARCHITECTURE §1 frontend directory + route list (frontend rows only) and this plan's status block.

### 1.7 Backend baseline

All backend Plans 03–07 merged; full suite 974 passed at HEAD. Routers registered in `main.py`: `transactions, approvals, delivery, evidence, evidence_submit, disputes, auth, entities, participants, invitations, reviews, rule_sets, ratifications, payment_ops, extraction_ops`. `LEGACY_CAPABILITY_ACCESS_ENABLED` default **false** — every legacy capability-token endpoint is out of scope for this frontend program.

---

## 2. Complete frontend program boundary

### Included (across the three PRs)

- Authenticated contract upload + account_v2 transaction creation; transaction list; transaction detail shell with section navigation; extraction/lifecycle status incl. stuck-extraction retry. (PR 1)
- Invitation create/preview/accept/revoke incl. expired/revoked/superseded/not-acceptable states; participant declared profile + confirm. (PR 1)
- Extracted-vs-declared party comparison panel; validator findings; manual-review case list + actions; rule revision + revalidation; ratification package build/view (hash, funding schedule, units/tranches, release mode); buyer/seller ratification; funding/activation lifecycle visibility; tracking-policy display/selection/locking **[currently BLOCKED — see §14.1]**. (PR 2)
- Milestone & funding-unit timeline (projection from package schedule + events); e-irsaliye and video evidence submission; evidence state/review status; evidence bundle view + immutable snapshot creation; dispute open/list/action timeline; payment reconcile; release retry; undo/refund request → bilateral approval → execute; redacted Moka trace panel; settled/refunded/blocked/recovery end states; demo scenario support. (PR 3)

### Explicitly excluded

- All `legacy_v1` capability-token views (`/t/:id/party`, `/t/:id/manager`, legacy delivery/approvals/evidence endpoints) — flag default false.
- Anonymous demo dashboard (`DEMO_PUBLIC_DASHBOARD`).
- Any backend change (routes, schemas, services, migrations). Where a required flow lacks a backend contract, the child plan marks it BLOCKED or specifies an explicit unsupported-state UI — it never invents an API.
- Redux/react-query/SWR or any global cache framework; optimistic financial/ratification state; websocket/live updates.
- Backend static-serving of the SPA; production deploy topology.
- Plan 09 scope (rate limiting, email verification, password reset UI, retention).
- Platform reviewer/admin dedicated console. Review/payment actions that require `platform_role ∈ {reviewer, admin}` are rendered inside the transaction shell and rely on backend 403s; no separate admin routes.

---

## 3. Global backend contract index

Full field-level contracts live in the child plans (column "Child §C"). Evidence = router file + primary test file.

| # | Operation | Method & route | PR | Evidence | Child |
|---|---|---|---|---|---|
| T1 | Create transaction (account_v2, multipart) | `POST /api/transactions` | 1 | `routers/transactions.py:364` · `tests/test_transaction_ownership_cutover.py` | 08b1 §C1 |
| T2 | List transactions (assignment-scoped) | `GET /api/transactions` | 1 | `routers/transactions.py:393` · `tests/test_transaction_ownership_cutover.py` | 08b1 §C2 |
| T3 | Transaction detail | `GET /api/transactions/{id}` | 1 | `routers/transactions.py:506` · `tests/test_transaction_ownership_cutover.py` | 08b1 §C3 |
| T4 | Extraction retry | `POST /api/transactions/{id}/extraction/retry` | 1 | `routers/extraction_ops.py` · `tests/test_extraction_job_recovery.py` | 08b1 §C4 |
| I1 | Create invitation | `POST /api/transactions/{id}/invitations` | 1 | `routers/invitations.py:53` · `tests/test_invitations_router.py` | 08b1 §C5 |
| I2 | Preview invitation (no auth) | `GET /api/invitations/{token}/preview` | 1 | `routers/invitations.py:86` · `tests/test_invitation_service.py` | 08b1 §C6 |
| I3 | Accept invitation | `POST /api/invitations/{token}/accept` | 1 | `routers/invitations.py:94` · `tests/test_participant_service.py` | 08b1 §C7 |
| I4 | Revoke invitation | `POST /api/transactions/{id}/invitations/{invitation_id}/revoke` | 1 | `routers/invitations.py:116` · `tests/test_invitations_router.py` | 08b1 §C8 |
| P1 | List participants (public view) | `GET /api/transactions/{id}/participants` | 1 | `routers/participants.py:93` · `tests/test_participants_router.py` | 08b1 §C9 |
| P2 | Update my declared profile | `PUT /api/transactions/{id}/participants/me/profile` | 1 | `routers/participants.py:109` · `tests/test_participants_router.py` | 08b1 §C10 |
| P3 | Confirm my profile | `POST /api/transactions/{id}/participants/me/confirm` | 1 | `routers/participants.py:127` · `tests/test_participants_router.py` | 08b1 §C11 |
| R1 | List review cases + actions | `GET /api/transactions/{id}/reviews` | 2 | `routers/reviews.py:81` · `tests/test_reviews_router.py` | 08b2 §C1 |
| R2 | Submit review action | `POST /api/reviews/{review_case_id}/actions` | 2 | `routers/reviews.py:100` · `tests/test_reviews_router.py`, `tests/test_review_resolution_e2e.py` | 08b2 §C2 |
| RS1 | Create rule revision | `POST /api/transactions/{id}/rule-sets/{version_id}/revisions` | 2 | `routers/rule_sets.py:372` · `tests/test_rule_revision_endpoints.py` | 08b2 §C3 — **BLOCKED (B2a + B2b)** |
| RS2 | Revalidate rule version | `POST /api/transactions/{id}/rule-sets/{version_id}/validate` | 2 | `routers/rule_sets.py:395` · `tests/test_rule_revision_endpoints.py` | 08b2 §C4 — **BLOCKED (B2a)** |
| TP1 | Configure tracking policy (account) | **MISSING — no account_v2 endpoint** | 2 | see §14.1 blocker B1 | 08b2 §D |
| TP2 | Lock tracking policy (account) | **MISSING — no account_v2 endpoint** | 2 | see §14.1 blocker B1 | 08b2 §D |
| RP1 | Build/open ratification package | `POST /api/transactions/{id}/ratification-packages` | 2 | `routers/ratifications.py:137` · `tests/test_ratification_package.py` | 08b2 §C5 |
| RP2 | Get current package | `GET /api/transactions/{id}/ratification-packages/current` | 2 | `routers/ratifications.py:183` · `tests/test_ratifications.py` | 08b2 §C6 |
| RP3 | Submit ratification | `POST /api/ratification-packages/{package_id}/ratifications` | 2 | `routers/ratifications.py:198` · `tests/test_ratifications.py` | 08b2 §C7 |
| E1 | Submit e-irsaliye evidence | `POST /api/transactions/{id}/evidence/e-irsaliye` | 3 | `routers/evidence_submit.py:186` · `tests/test_evidence_submit_api.py` | 08c §C1 |
| E2 | Submit video evidence (multipart) | `POST /api/transactions/{id}/evidence/video` | 3 | `routers/evidence_submit.py:248` · `tests/test_evidence_submit_api.py` | 08c §C2 |
| E3 | Get evidence bundle | `GET /api/transactions/{id}/evidence-bundle` | 3 | `routers/evidence.py:63` · `tests/test_evidence_bundle.py` | 08c §C3 |
| E4 | Create evidence snapshot | `POST /api/transactions/{id}/evidence-snapshots` | 3 | `routers/evidence.py:75` · `tests/test_evidence_snapshot_api.py` | 08c §C4 |
| D1 | Open dispute | `POST /api/transactions/{id}/disputes` | 3 | `routers/disputes.py:191` · `tests/test_disputes_api.py` | 08c §C5 |
| D2 | List disputes | `GET /api/transactions/{id}/disputes` | 3 | `routers/disputes.py:216` · `tests/test_disputes_api.py` | 08c §C6 |
| D3 | Submit dispute action | `POST /api/disputes/{dispute_id}/actions` | 3 | `routers/disputes.py:229` · `tests/test_disputes_api.py` | 08c §C7 |
| PO1 | Reconcile transaction payments | `POST /api/transactions/{id}/payments/reconcile` | 3 | `routers/payment_ops.py:79` · `tests/test_payment_ops_api.py`, `tests/test_payment_reconciliation.py` | 08c §C8 |
| PO2 | Retry release instruction | `POST /api/release-instructions/{id}/retry` | 3 | `routers/payment_ops.py:123` · `tests/test_payment_operations.py` | 08c §C9 — **BLOCKED (B3/B7 id discovery)** |
| PO3 | Request undo | `POST /api/funding-units/{id}/undo-request` | 3 | `routers/payment_ops.py:171` · `tests/test_payment_ops_api.py` | 08c §C10 — **BLOCKED (B7 id discovery)** |
| PO4 | Request refund | `POST /api/funding-units/{id}/refund-request` | 3 | `routers/payment_ops.py:190` · `tests/test_payment_ops_api.py` | 08c §C10 — **BLOCKED (B7 id discovery)** |
| PO5 | Approve payment resolution | `POST /api/payment-resolutions/{id}/approvals` | 3 | `routers/payment_ops.py:209` · `tests/test_payment_operations.py` | 08c §C11 — **BLOCKED (B6 resolution read)** |
| PO6 | Execute payment resolution | `POST /api/payment-resolutions/{id}/execute` | 3 | `routers/payment_ops.py:225` · `tests/test_payment_operations.py` | 08c §C12 — **BLOCKED (B6 resolution read)** |
| PO7 | Payment trace (redacted) | `GET /api/transactions/{id}/payment-trace` | 3 | `routers/payment_ops.py:248` · `tests/test_payment_ops_api.py` | 08c §C13 |

Auth/entity operations (`/api/auth/*`, `/api/entities*`) are already consumed by Phase 8A and are not re-specified; evidence `routers/auth.py`, `routers/entities.py`, `tests/test_auth_router.py`, `tests/test_entities_router.py`.

---

## 4. Shared route architecture (final state after PR 3)

| Route | Introduced | Content |
|---|---|---|
| `/` `/register` `/login` `/logout` `/me` `/entities/new` `/entities/:entityId` `/session-required` `/permission-denied` `/conflict` `*` | 8A (exists) | unchanged |
| `/transactions` | PR 1 | scoped list + "Yeni işlem" CTA |
| `/transactions/new` | PR 1 | upload + create form |
| `/transactions/:transactionId` | PR 1 | detail shell; index redirects to `overview` |
| `/transactions/:transactionId/overview` | PR 1 | state, extraction summary, validator status, event timeline, extraction retry |
| `/transactions/:transactionId/parties` | PR 1 | participants, invitation panel, my-profile/confirm |
| `/transactions/:transactionId/rules` | PR 2 | party comparison, validator findings, review cases/actions, rule revision (blocked parts per 08b2 §D) |
| `/transactions/:transactionId/ratification` | PR 2 | tracking-policy summary (read from package projection), package build/view, ratify |
| `/transactions/:transactionId/fulfillment` | PR 3 | milestone/funding-unit timeline, evidence upload + records, bundle/snapshot |
| `/transactions/:transactionId/disputes` | PR 3 | dispute open/list/action timeline |
| `/transactions/:transactionId/payments` | PR 3 | reconcile, resolutions, retry, redacted trace |
| `/invitations/:token` | PR 1 | preview + accept (public route; RequireAuth only for the accept action) |

Rules: section slugs are path segments (deep-linkable, browser-back friendly). Sections not yet shipped are simply absent from `SectionNav` (PR 1 renders only `overview`/`parties`). The shell must not hard-code the section list — it takes a `sections` prop (see §5). Invitation tokens appear **only** in `/invitations/:token`; that route must never send the token to any endpoint other than I2/I3, never `console.log` it, and must `navigate(..., { replace: true })` away after accept so the token drops out of history.

---

## 5. Shared component architecture

All new shared components live in `code/frontend/src/components/`. Pages live in `src/pages/transactions/` (PR 1 creates the directory).

| Component | Responsibility | Public props | Data ownership | First PR | Extension seam |
|---|---|---|---|---|---|
| `TransactionShell` (`components/TransactionShell.tsx`) | Detail-page frame: heading with id/state badge, `SectionNav`, `<Outlet context={shell}>` | `transactionId: string` (from route) | Owns the `GET /transactions/{id}` read + `refresh()`; exposes `{detail, refresh, loading, error}` via router outlet context (typed helper `useTransactionShell()`) | PR 1 | PR 2/3 add section routes; shell unchanged except section registry list |
| `SectionNav` (`components/SectionNav.tsx`) | Accessible tab-style nav of section links | `sections: {slug, label}[]`, `basePath: string` | none (pure) | PR 1 | PR 2/3 append entries where the shell registers sections |
| `StatusBadge` (`components/StatusBadge.tsx`) | Color+text badge for any enum status | `value: string`, `map: Record<string,{label: string; tone: "info"\|"success"\|"warning"\|"danger"\|"neutral"}>` | none (pure); per-domain maps live in `src/lib/statusMaps.ts` | PR 1 | PR 2/3 add new maps to `statusMaps.ts` only |
| `Timeline` (`components/Timeline.tsx`) | Ordered event list (`<ol>`), per-item icon-free tone + timestamp + optional details | `items: {id: string\|number; title: string; tone?: ...; timestamp: string; children?: ReactNode}[]`, `emptyLabel: string` | none (pure) | PR 1 (events) | PR 3 reuses for milestone/dispute/trace timelines |
| `ConfirmDialog` (`components/ConfirmDialog.tsx`) | Accessible modal confirm (focus trap, `Esc`, `aria-modal`, initial focus on cancel) | `open`, `title`, `description`, `confirmLabel`, `tone?: "default"\|"danger"`, `requireText?: string` (typed confirmation for financial actions), `busy?: boolean`, `onConfirm`, `onCancel` | none | PR 1 (used by revoke) | PR 2 ratify; PR 3 financial ops use `requireText` |
| `EmptyState` (add to `components/Feedback.tsx`) | Consistent empty panel | `title`, `description?`, `action?: ReactNode` | none | PR 1 | reused everywhere |
| `KeyValueGrid` (add to `components/Feedback.tsx`) | Responsive `dl` grid wrapping existing `Info` | `items: {label: string; value: ReactNode}[]` | none | PR 1 | reused |
| `ResponsiveTable` (`components/ResponsiveTable.tsx`) | Table in `overflow-x-auto` container with `min-w`, caption for a11y | `caption: string`, `head: string[]`, `rows: {key: string; cells: ReactNode[]}[]`, `emptyLabel: string` | none | PR 1 (list page) | PR 2 schedule table; PR 3 trace/records |
| `CommandPanel` pattern (convention, not a component) | Mutation form block: fieldset + submit + `FormError` + success `Notice`; disabled with reason when unavailable | — | page-local | PR 1 | documented in child plans per command |
| `useAsyncData` (`src/lib/useAsyncData.ts`) | Route-level read hook: `{data, loading, error, refresh}`; stale-response guard via closure flag; re-runs on dep change | `useAsyncData<T>(fetcher: () => Promise<T>, deps: unknown[])` | page/shell | PR 1 | all later reads |
| `usePolling` (`src/lib/usePolling.ts`) | Conditional interval refresh (only while `active`), cleans up on unmount | `usePolling(callback, {active: boolean; intervalMs: number})` | page | PR 1 (extracting state) | PR 3 optional for unknown payment states (manual refresh preferred; see §8) |

Disabled-command rule (all PRs): when a command is hidden/disabled because of backend state, the UI shows the reason as text from a static Turkish map keyed by the *backend-provided* state/error code — the frontend never computes permission itself, it renders what the backend enforced (403/409 after attempt, or state value from a read).

---

## 6. Shared TypeScript domain architecture

Backend field names are used verbatim (snake_case) — no adapter layer. `types/api.ts` keeps 8A types; new domain types go in new files:

- `src/types/transactions.ts` (PR 1): `LifecycleVersion = "legacy_v1" | "account_v2"`; `AccountState = "preparation" | "uploaded" | "extracting" | "awaiting_review" | "awaiting_approval" | "awaiting_ratification" | "funding_pending" | "active" | "settled" | "rejected" | "cancelled"` (string union kept open with `| (string & {})` so unknown states render as neutral badge instead of crashing); `TransactionListItem`, `TransactionDetail`, `TransactionEvent`, `RedactedExtraction` (+ nested `ExtractionParties`, `CommercialTerms`, `PaymentRule` — mirror of §4.2 redacted projection, no `tax_id`, no `source_quote`), `ValidatorReport {status: "PASS"|"NEEDS_REVIEW"|"REJECT"|null; findings: ValidatorFinding[]|null}`, `CreateTransactionResponse`, `ExtractionRetryResponse`.
- `src/types/participants.ts` (PR 1): `ParticipantRole`, `ParticipantStatus = "invited"|"profile_incomplete"|"ready"|"confirmed"`, `InvitationStatus`, `PartyProfileSnapshot`, `Participant` (full, own-party mutations), `ParticipantPublicView`, `InvitationCreateRequest/Result`, `InvitationPreview`, `InvitationAcceptRequest`.
- `src/types/reviews.ts` (PR 2): `ReviewPhase`, `ReviewSourceType`, `ReviewSeverity`, `ReviewStatus`, `ReviewActionType`, `ReviewCase`, `ReviewAction`, `ReviewCaseWithActions`, `ReviewActionRequest`.
- `src/types/ratification.ts` (PR 2): `RatificationPackageStatus`, `RatificationPackagePublicView`, `CanonicalPackagePayload` (typed subset actually rendered: `funding_schedule`, `commercial_summary`, `tracking_policy.snapshot`, `rule_set`, hashes), `FundingScheduleMilestone`, `FundingUnitSpec`, `RatificationOutcome`, `FundingScheduleSpec` request types.
- `src/types/rules.ts` (PR 2): `RuleSetVersionPublicView`, `ExtractionJSONInput` (full §4.2 payload for revision body).
- `src/types/evidence.ts` (PR 3): `EvidenceRecordPublicView`, `EvidenceBundle`, `EvidenceSnapshotResponse`.
- `src/types/disputes.ts` (PR 3): `DisputeOpenRequest`, `DisputePublicView`, `DisputeActionRequest`, `DisputeActionPublicView`.
- `src/types/payments.ts` (PR 3): `ReconcileResponse`, `ReconcileUnitResult`, `ReleaseRetryResponse`, `PaymentResolutionView`, `ResolutionExecuteResponse`, `PaymentTraceResponse`, `PaymentTraceOperation`.

Formatting boundaries (PR 1 creates `src/lib/format.ts`): `formatDateTime(iso: string): string` (Turkish locale, `Intl.DateTimeFormat("tr-TR", {dateStyle:"medium", timeStyle:"short"})`, invalid input → `"—"`); `formatAmountMinor(amountMinor: number, currency: string): string` (divide by 100 only for display, `Intl.NumberFormat("tr-TR", {style:"currency"})`, unknown currency falls back to plain number + code — the frontend never does financial arithmetic beyond this display division); `formatPercentBps(basisPoints: number)`. All monetary/percentage values shown come from backend fields; no client-side sums/derivations.

PR-specific one-off types stay in their page files; anything used by ≥2 files goes in `src/types/*`.

---

## 7. Shared API-module architecture

One file per domain in `src/api/`, each function a thin wrapper over `apiRequest` with exact URL, method, csrf flag, request/response types. Final set:

| Module | PR | Functions |
|---|---|---|
| `api/client.ts` | 8A | unchanged (extend only if a child plan explicitly says so — none do) |
| `api/transactions.ts` | 1 | `createTransaction(form: FormData)`, `listTransactions()`, `getTransaction(id)`, `retryExtraction(id)` |
| `api/invitations.ts` | 1 | `createInvitation(transactionId, body)`, `previewInvitation(token)`, `acceptInvitation(token, body)`, `revokeInvitation(transactionId, invitationId)` |
| `api/participants.ts` | 1 | `listParticipants(transactionId)`, `updateMyProfile(transactionId, body)`, `confirmMyProfile(transactionId)` |
| `api/reviews.ts` | 2 | `listReviews(transactionId)`, `submitReviewAction(reviewCaseId, body)` |
| `api/rules.ts` | 2 | `createRuleRevision(transactionId, versionId, payload)`, `validateRuleVersion(transactionId, versionId)` *(functions specified; page wiring blocked, 08b2 §D)* |
| `api/ratification.ts` | 2 | `buildRatificationPackage(transactionId, body)`, `getCurrentRatificationPackage(transactionId)`, `submitRatification(packageId)` |
| `api/evidence.ts` | 3 | `submitEIrsaliye(transactionId, body)`, `submitVideoEvidence(transactionId, form: FormData)`, `getEvidenceBundle(transactionId)`, `createEvidenceSnapshot(transactionId)` |
| `api/disputes.ts` | 3 | `openDispute(transactionId, body)`, `listDisputes(transactionId)`, `submitDisputeAction(disputeId, body)` |
| `api/payments.ts` | 3 | `reconcilePayments(transactionId)`, `retryReleaseInstruction(instructionId)`, `requestUndo(fundingUnitId, body)`, `requestRefund(fundingUnitId, body)`, `approveResolution(resolutionId)`, `executeResolution(resolutionId)`, `getPaymentTrace(transactionId)` |

Conventions: every mutation passes `csrf: true` and `redirectOnError: false` (page-local error UI); reads use default redirect behavior except where a child plan says otherwise (e.g. invitation preview uses `redirectOnError: false` so a 404 renders inline). Multipart posts pass a `FormData` body and never set Content-Type manually.

---

## 8. Shared state and data-loading strategy

- **State ownership:** `AuthContext` + `EntityContext` remain the only app-level contexts. Everything else is route/page-local state via `useAsyncData` + `useState`. No new context except the shell's outlet context (not a React context; router `useOutletContext`).
- **Route-level loading:** each section page issues its reads on mount; `TransactionShell` owns the detail read and passes it down, so section pages only fetch their *own* extra resources (participants, reviews, package, bundle, disputes, trace). Independent reads run in parallel (`Promise.all` inside one `useAsyncData` fetcher or two hooks); sequential only where an id from read A is needed for read B (documented per page in child plans).
- **Mutation refresh:** on success, call the owning `refresh()` functions for every read whose data the mutation can change — always including `shell.refresh()` when the mutation can move lifecycle state (create invitation → participants; confirm → participants + shell + reviews; ratify → package + shell; evidence submit → bundle/records + shell; dispute/review resolve → own list + shell). No optimistic updates anywhere; financial buttons disable while in-flight (`busy`).
- **Failure:** mutation errors render page-locally (`FormError`/`Notice`), `redirectOnError: false`. 409s additionally offer a "Verileri yenile" button that calls the relevant `refresh()` — conflict = stale view until refreshed.
- **Cancellation/stale guard:** `useAsyncData` ignores resolutions after unmount/dep-change (closure flag, the 8A `active` pattern). No AbortController requirement (SQLite backend, cheap requests); guard against *applying* stale data, not against the request itself.
- **Lifecycle refresh / polling:** only the overview section polls, and only while `detail.state ∈ {"uploaded","extracting"}` — `usePolling` at 4000 ms, stops on any other state or on unmount. All other "waiting" states (funding_pending, approval_unknown…) use a manual "Yenile" button; payment outcomes are human-paced operator flows and polling would hammer reconcile semantics.
- **Conflict recovery:** stale-parent (`STALE_RULE_SET_VERSION`), superseded package (`PACKAGE_SUPERSEDED`), `REVIEW_CASE_CLOSED`, `INVITATION_NOT_ACCEPTABLE` etc. are expected 409s → inline message + refresh CTA; never auto-retry a mutation.
- **Why no larger framework:** ≤ 2 reads per section, no cross-page cache coherence requirement (refresh-on-mutation suffices), backend is single-user-scale SQLite; react-query/Redux would add invalidation semantics we'd have to fight to keep "backend is the only truth". This conclusion is binding for all three PRs.

---

## 9. Shared security model (frontend obligations)

1. **Auth:** session cookie only; `RequireAuth` wraps every authenticated route; 401 → `/session-required`. No token storage anywhere.
2. **CSRF:** every mutation through `csrf: true` (client reads `m4t_csrf`). Never bypass; never read/write other cookies.
3. **Acting entity:** only via `EntityContext` → `X-Acting-Entity-ID`. Pages that act "as entity" (create tx, evidence, dispute, ratify, rule ops) must show the currently selected entity near the submit button so the user sees whose behalf they act on; if no entity selected, the command is disabled with reason.
4. **Invitation tokens:** live only in `/invitations/:token`; sent only to preview/accept; `replace: true` navigation after accept; never persisted, never in error reports/analytics (none exist), never interpolated into other URLs. The `invite_link` returned by create is shown once for copy — with a Turkish notice that it is secret and single-use.
5. **Authorization failures:** 403 on a section read → in-shell permission panel (not a crash); commands render but on 403 show the backend message; the frontend never pre-computes "you are manager". Role-dependent visibility may *soft-hide* commands only based on data the backend already returned (e.g. `user.platform_role` from `GET /auth/me` for platform-only review actions, or own participant role from a mutation response) and must still handle 403.
6. **Sensitive data:** never render `storage_ref`, raw payloads, markdown, tokens, `client_ip_hash`/`user_agent_summary`. **Tax-id rule (precise):** another party's full tax id is never rendered anywhere; entity identity uses only `tax_identifier_last4` masked form; the *user's own explicitly-entered declared* `tax_id` may appear only inside their own profile edit form (input they typed / their own mutation response) — never in participant lists, transaction projections, events, or logs. **`source_quote` is never rendered from any account endpoint**, including the evidence bundle (which currently returns a masked variant — see §14.1 B8; the frontend drops the field at the type/render layer). If an unexpected field appears, typed interfaces simply don't render it (no `JSON.stringify` dumps of unknown objects into the DOM; the only exception is the payment-trace redacted request/response `<pre>` viewer — a backend-guaranteed redacted projection, see 08c; the bundle viewer renders typed sub-views only).
7. **Financial commands** (ratify, undo/refund request/approve/execute, retry, reconcile): `ConfirmDialog` (danger tone; `requireText` for execute), explicit result rendering incl. `unknown` outcome as **"belirsiz — mutabakat gerekli"** (never as failure), buttons disabled in-flight, no auto-retry.
8. **Provider traces:** render only fields from `GET .../payment-trace` (already redacted); label the panel "public contract simulation".
9. **Replay/conflict:** idempotent endpoints (invitation accept replay, evidence replay, ratification replay, snapshot replay) treat a 200-with-existing-resource as success and refresh; 409 conflict codes get specific Turkish copy per child plan tables.
10. **Error bodies:** only `error.userMessage` (envelope `message` or generic) is shown — raw `detail` objects are consumed programmatically (e.g. `PolicyConflict.conflicts` codes) through typed guards, never dumped.

---

## 10. Shared accessibility and responsive requirements

- **Keyboard:** every command reachable by Tab; `ConfirmDialog` traps focus, `Esc` cancels, `Enter` does not auto-confirm destructive dialogs (confirm button must be focused explicitly or via typed text).
- **Focus movement:** after route change, focus the page `<h1>` (`tabIndex={-1}` + `ref.focus()` in `PageHeading` — PR 1 adds an optional `autoFocus` prop); after a mutation error, focus the error `Notice` (`role="alert"`).
- **Error summaries:** form-level `FormError` renders with `role="alert"`; field-level constraints described via `aria-describedby`.
- **Status announcements:** async panels use `aria-busy`; success notices `role="status"`. Polling updates must not steal focus.
- **Dialogs:** `role="dialog"` `aria-modal="true"` `aria-labelledby`/`aria-describedby`; return focus to the trigger on close.
- **Tabs/section nav:** `SectionNav` is a `<nav aria-label="İşlem bölümleri">` of real links (`aria-current="page"` on active) — links, not ARIA tabs, because sections are routes.
- **Responsive tables:** `ResponsiveTable` wraps in `overflow-x-auto`; ≤ 640 px the transaction list switches to stacked cards (list page only; other tables keep horizontal scroll).
- **Timeline:** semantic `<ol>`; tone conveyed by label text + color, never color alone.
- **Color-independent status:** `StatusBadge` always renders the Turkish label text; tone is additive.
- Layout continues the 8A dark theme utility classes; max width `max-w-6xl`; forms `max-w-2xl`.

---

## 11. Cross-PR dependency matrix

| Shared file | Created | Extended by | Extension seam | Backward-compat requirement |
|---|---|---|---|---|
| `components/TransactionShell.tsx` | PR 1 | PR 2, PR 3 | section registry array + new `<Route>` children in `AppRoutes.tsx` | outlet context shape `{detail, refresh, loading, error}` frozen; PR 2/3 may add fields, never rename |
| `components/SectionNav.tsx` | PR 1 | — (data-driven) | `sections` prop | props frozen |
| `components/StatusBadge.tsx` + `lib/statusMaps.ts` | PR 1 | PR 2 (package/review maps), PR 3 (evidence/dispute/unit maps) | add exported maps | existing map keys/labels unchanged |
| `components/Timeline.tsx` | PR 1 | PR 3 | `items` prop | props frozen |
| `components/ConfirmDialog.tsx` | PR 1 | PR 3 (uses `requireText`) | props already include it | props frozen |
| `components/Feedback.tsx` (`EmptyState`, `KeyValueGrid`) | PR 1 additions | PR 2/3 use | — | existing exports unchanged |
| `components/ResponsiveTable.tsx` | PR 1 | PR 2/3 use | — | props frozen |
| `lib/useAsyncData.ts`, `lib/usePolling.ts`, `lib/format.ts` | PR 1 | PR 2/3 use | new pure functions may be added to `format.ts` | signatures frozen |
| `routes/AppRoutes.tsx` | 8A | PR 1/2/3 each add routes | nested children under `/transactions/:transactionId` | existing routes untouched |
| `types/*.ts` | per §6 | later PRs add new files only | new files | existing type names/fields never changed, only added |
| `api/*.ts` | per §7 | later PRs add new files only | new files | function signatures frozen once merged |
| `api/client.ts`, `AuthContext`, `EntityContext` | 8A | none | — | not modified by any PR |

---

## 12. Three-PR delivery strategy

Supersedes the five-slice split in `plans/ready/08_frontend_vertical_slices.md` (Slice 2 → PR 1; Slices 3+4 → PR 2; Slices 5+6 → PR 3). Exactly three implementation PRs; no further slicing.

| | PR 1 | PR 2 | PR 3 |
|---|---|---|---|
| Branch | `feat/frontend-deal-core` | `feat/frontend-rules-ratification` | `feat/frontend-fulfillment-operations` |
| Base | integration base (see §1: `program/domain-evolution-v2`, or `master` once it contains `ebf6dc7`) | same base after PR 1 merge | same base after PR 2 merge |
| Prerequisites | none | PR 1 merged; blockers B1+B2a+B2b resolved backend-side (§14.1) | PR 2 merged; blockers B6+B7+B5+B3 resolved and B8 decided backend-side (§14.1) |
| Expected commits | 3 (see 08b1 §A) | 3 (see 08b2 §A) | 3 (see 08c §A) |
| Merge gate | frontend CI green (lint, typecheck, test, build) + review + honest manual smoke report (08b1 §M) | same + blocker resolution verified in preflight | same |
| Browser smoke | 08b1 §M | 08b2 §M | 08c §M |
| Handoff | detail-shell outlet context + section registry documented in PR description | package/reviews components listed for PR 3 reuse | demo guide note in PR description |

Each PR runs the full child-plan §N verification before push. `git status --short` must show only `code/frontend/**` changes plus that plan's status-block edit and the two doc-sync files (ARCHITECTURE §1 route list; the child plan moved to `plans/done/`).

---

## 13. Global acceptance scenario (browser, after PR 3)

Adapted from v2 §20 (steps 1–27) to actual contracts. Two browsers/profiles: Berke (manager+buyer, ABC A.Ş.), Yusuf (seller, XYZ Ltd.) — `scripts/seed_demo_users.py` seeds both.

1. Berke registers/logs in; selects ABC A.Ş. in the shell selector.
2. `/transactions/new`: uploads contract (`.md` fixture for fake pipeline), role buyer, counterparty email Yusuf's; sees created transaction + one-time invite link.
3. `/transactions/:id/overview`: state `uploaded → extracting → awaiting_review|awaiting_approval` via polling; validator status visible. (If stuck `extracting`, "Extraction'ı yeniden dene" appears for manager.)
4. Yusuf opens `/invitations/:token` — preview shows role + transaction reference only; logs in, selects XYZ Ltd., accepts; lands on the transaction.
5. Both fill declared profile in `parties` and confirm; party-mismatch review (if any) appears in `rules` and is resolved per 08b2.
6. Berke revises rules if NEEDS_REVIEW (08b2 flow) and revalidates → state returns to a package-eligible state.
7. Tracking policy configured + locked (**pending blocker B1**; until then this step is only possible via backend-side seeding).
8. Berke builds the ratification package in `ratification`; both parties see identical `package_hash`, funding schedule (milestones/units/tranches, release modes), commercial summary.
9. Berke ratifies as ABC; Yusuf ratifies as XYZ → `funding_triggered: true`; overview shows `funding_pending → active`; events show `funding_required`/`funding_units_pool_created`.
10. Yusuf (seller) submits e-irsaliye in `fulfillment` (quantity per contract); timeline shows evidence verified; on threshold, units approve; events show `funding_units_approved`.
11. Video evidence with a `hasarli` fixture filename → `review_required` record + blocking settlement review visible in `rules`/reviews; platform reviewer resolves with `VIDEO_FALSE_POSITIVE` (or dispute path: Yusuf/Berke approver opens dispute in `disputes`, later resolves).
12. Remaining releases complete → `transaction_settled` event; overview badge `settled`.
13. `payments`: reconcile button for unknown units; redacted Moka trace lists create/approve/detail operations with `attempt_no`/`outcome`; undo/refund request → approvals → execute demonstrated on a demo unit (fault-injection fixture).
14. `fulfillment`: evidence bundle renders; explicit snapshot created; replay returns same `snapshot_hash` (`created: false`).
15. Throughout: no tokens/tax-ids/raw payloads anywhere in the DOM; 401/403/409 produce the intentional screens/messages.

---

## 14. Global risks

### 14.1 Backend contract blockers (historical discrepancies; resolved by the 2026-07-12 backend closure)

**Blocking 08b2 (PR 2):**
- **B1 — account_v2 tracking-policy configure/lock API missing.** The only endpoints (`PUT /api/transactions/{id}/tracking-policy`, `POST .../tracking-policy/lock`, `routers/transactions.py:672,729`) require a legacy capability `manager_token` in the body and `LEGACY_CAPABILITY_ACCESS_ENABLED` (default false); account_v2 rows have `manager_token = NULL`, so `resolve_manager` always 403s. Yet `ratification_package._build_inputs` fails closed with `TRACKING_POLICY_NOT_LOCKED` (`services/ratification_package.py:271-276`), and backend tests lock policy via raw SQL (`tests/test_ratification_package.py:83`). Consequence: the entire account ratification→funding→settlement chain is not browser-drivable. Resolution needed: session+CSRF creator-manager policy endpoints.
- **B2a — current rule-set version id / version history not readable.** `POST .../rule-sets/{version_id}/revisions|validate` need `version_id`, but no account read exposes it: `GET /transactions/{id}` returns only redacted extraction + `{status, findings}`; `RuleSetVersionPublicView` is returned only *by* the revision endpoints; the package payload contains `rule_set.id` but a package requires a locked policy (B1) and is absent exactly when revision matters (NEEDS_REVIEW). Also no version *list* endpoint exists for the required "rule-set version list/diff" UI.
- **B2b — no safe revision contract for `source_quote`.** The revision body is the full `ExtractionJSON`, whose `PaymentRule.source_quote` is a **required** field (`schemas/extraction.py:98`), and the service persists the submitted payload verbatim as the new immutable version — it does not merge/preserve parent quotes. But no account read returns the original quotes (redacted reads drop the field entirely; the bundle returns only a *masked* variant that must never be round-tripped back as content). A frontend that submits `""` or masked text would destroy the contractual citations in the new version. Resolution needed backend-side: either `source_quote` optional-on-revision with parent-preservation semantics, or a creator-manager-only full edit projection.

**Blocking 08c (PR 3):**
- **B6 — payment resolutions not discoverable/listable.** `POST .../approvals` and `.../execute` need `resolution_id`, which appears only in the requesting manager's POST response. The counterparty approver (a different user) has no read that surfaces it: review case `source_id` is the *funding-unit* id, events don't carry resolution ids, and there is no `GET` for resolutions. The mandated bilateral undo/refund approval flow is therefore not completable across users/reloads. Resolution needed: assignment-scoped resolution list/detail read (id, unit, operation_type, status, approvals, review_case_id).
- **B7 — funding-unit ids not projected for healthy units.** `POST /api/funding-units/{id}/undo-request|refund-request` needs a real `funding_unit_id`, but reconcile results cover only `pool_creation_unknown|approval_unknown` units and review cases exist only for failures; the package payload's unit rows carry `sequence`, not DB ids. A normal `approved` unit — the primary undo/refund scenario — has no id source. Resolution needed: funding-unit projection read (id, milestone_id, sequence, status, amount_minor, currency, release_instruction_id if any).
- **B5 (upgraded to blocking) — milestone id ↔ package rule_index mapping missing.** Package milestones carry `rule_index` only; evidence records carry DB `milestone_id` only; nothing maps them. In any multi-milestone transaction the fulfillment timeline cannot bind evidence to milestones, evidence forms cannot offer milestone choices, and units cannot be grouped under their milestone. Single-milestone demos work, but the mandated timeline scope does not. Covered by the same funding-unit/milestone projection as B7.
- **B3 — `release_instructions.id` not exposed by any read** (trace lacks it; reconcile returns unit ids only), so "safe release retry" has no id source beyond operator paste. Covered by the B7 projection.
- **B8 — evidence-bundle `source_quote` conflicts with the binding invariant.** AGENTS/`extraction_projection.py` state quotes return only on capability-token endpoints, yet `build_bundle_core` builds the account bundle with `include_source_quote=True` and serves it to session actors (`services/evidence.py:280-282`). Until the team consciously resolves this backend-side, the frontend must **never render** `source_quote` from the bundle (08c is specified accordingly); flagged for an explicit backend/invariant decision.

**Non-blocking (documented limitations):**
- **B4 (PR 1):** no invitation list endpoint; revoke needs the `invitation_id` from the create response. UI keeps the last-created invitation in page state and reflects expired/revoked/superseded states through participant status + preview/accept error codes.
- **B9 (PR 1):** no `GET .../participants/me` — the declared own-profile cannot be re-read after reload (public list intentionally strips PII). 08b1 mitigates with an explicit overwrite guard (§H) and this stays a UX limitation; recommended backend read: own full participant projection.
- **B10 (PR 2, mitigated):** `RatificationPackagePublicView` lacks per-party ratification progress; 08b2 reads the existing assignment-scoped `GET .../evidence-bundle` and consumes only its `ratification_package.ratifications` block for "1/2 onayladı" display. A package-level summary field remains the cleaner backend fix.

**Recommended sequencing:** close B1/B2a/B2b/B6/B7+B5/B3 (+decide B8) in one narrow backend "frontend projection gap closure" PR **before** starting PR 2/PR 3 implementation; then re-run the child preflights (they gate on these contracts) and record the new contracts into the child §C tables.

### 14.2 Frontend architecture risks

Shell outlet-context churn across PRs (mitigated by frozen shape §11); multipart uploads bypass JSON typing (mitigated by dedicated helpers and tests); mixed error body shapes (envelope vs HTTPException string vs `PolicyConflict` detail) — child plans list which endpoints return which.

### 14.3 Security risks

Invitation token exposure via history/copy-paste (mitigated §9.4); accidental rendering of unknown backend fields (typed rendering only, §9.6); acting-entity mismatch causing confusing 403s (selected-entity indicator near commands, §9.3).

### 14.4 PR sequencing risks

Both PR 2 and PR 3 were blocked on the backend projection gaps recorded in §14.1. The narrow backend "frontend projection gap closure" is now recorded in §14.7; the child plans may proceed after their frontend-base prerequisites. Backend contract drift between planning and execution remains caught by each child plan's §B preflight.

### 14.5 Demo-data risks

Fake extraction fixture is approval-only (single milestone); multi-milestone/tranche demos need a contract fixture whose `payment_rules` produce ≥2 rules — 08c §M names the fixture requirement. Fault-injection demo tokens (`DEMO-TOKEN-TIMEOUT-AFTER-CREATE` etc.) only work with the mock-Moka topology; smoke sections state exact env.

### 14.6 Manual browser verification risks

`SESSION_COOKIE_SECURE=false`, `APP_ENCRYPTION_KEY`/`APP_HMAC_KEY` required (frontend README); single-worker uvicorn only; video analysis needs `VIDEO_PROVIDER=fake` filename hints. Smoke reports must be honest — a build is not visual proof (README rule).

## 14.7 Backend projection gap-closure status (2026-07-12)

The narrow backend closure PR `feat/backend-frontend-projection-gap-closure` resolves the frontend contract blockers without implementing frontend code. The frontend child plans remain in `plans/ready/` and are not marked done.

| Gap | Status after backend closure | Contract now available |
|---|---|---|
| B1 tracking policy | RESOLVED | Session/CSRF/creator-manager `GET`, `PUT`, and `POST .../tracking-policy/lock`; account body has no capability token |
| B2a/B2b rule versions and quotes | RESOLVED | Assignment-scoped `GET .../rule-sets`; dedicated revision request accepts omitted `source_quote` and merges the current parent by rule index before frozen-schema validation |
| B10 ratification progress | RESOLVED | Current package includes buyer/seller `{ratified, approved_at}` progress |
| B3/B5 milestone and release IDs | RESOLVED | Assignment-scoped `GET .../milestones` exposes milestone/unit IDs, rule mapping, status, amount, sequence, and nullable release-instruction ID |
| B6 payment resolutions | RESOLVED | Assignment-scoped payment-resolution list/detail reads include approvals and cross-transaction isolation |
| B7 healthy funding-unit IDs | RESOLVED | Same milestone projection exposes real funding-unit IDs for all current-package units |
| B8 account bundle quote invariant | RESOLVED | Account/session bundle and snapshots omit `source_quote`; only legacy capability compatibility retains it |

Readiness update: 08b2 is `READY_TO_IMPLEMENT` once its frontend PR 1 base is present; 08c remains `READY_TO_IMPLEMENT` and should consume the new projection reads instead of the former B3/B5/B6/B7 limitations.
