# 08B1 — Frontend Slice B1: Deal Core (PR 1)

> **Durum:** Uygulandı — 2026-07-12 · Branch `feat/frontend-deal-core` (base `program/domain-evolution-v2`) · Sapmalar: yok — task packet'leri §K sırasıyla, 3 commit (§A), tüm §N doğrulamaları yeşil. Bilinen kısıt: `GET participants/me` yok (B9) → profil overwrite-guard uygulandı (§H). Manuel tarayıcı duman testi PR açıklamasında dürüstçe raporlanır.
> **Master:** `plans/ready/08_frontend_completion_master_plan.md` (read it first; §1 baseline, §5–§10 shared architecture are binding)
> **Readiness:** `READY_TO_IMPLEMENT` (see end of file)

## A. Phase identity

- **PR title:** `feat(frontend): Slice B1 — deal core (transactions, invitations, participants)`
- **Branch:** `feat/frontend-deal-core`
- **Base:** the integration base per master plan §1 — `program/domain-evolution-v2`, or `master` if it now contains commit `ebf6dc7`. Verify: `git merge-base --is-ancestor ebf6dc7 <base>` must succeed (at planning time `origin/master` did NOT contain PR #67).
- **Prerequisite merged PR:** #67 (frontend foundation) — already merged
- **Included scope:** shared UI infrastructure (shell, nav, badges, timeline, dialog, table, hooks, format lib); `/transactions` list; `/transactions/new` upload+create; transaction detail shell with `overview` and `parties` sections; extraction retry; invitation create/preview/accept/revoke incl. expired/revoked/superseded/not-acceptable states; participant declared profile + confirm.
- **Excluded scope:** rules/reviews/ratification/policy UI (PR 2); evidence/disputes/payments UI (PR 3); any legacy capability view; any backend file.
- **Expected commits (exactly 3):**
  1. `feat(frontend): shared shell, primitives and data hooks` — components, lib, types/transactions+participants, api modules, route scaffolding, tests for pure helpers.
  2. `feat(frontend): transaction list, create and detail overview` — pages `/transactions`, `/transactions/new`, shell + overview section, extraction retry, tests.
  3. `feat(frontend): invitations and participants` — parties section, `/invitations/:token`, profile/confirm flows, DOM/component test layer (Task 8), README/doc-sync.

## B. Contract-drift preflight

Before writing code, verify each item below by opening the named file. Do **not** re-read the whole repo.

1. `code/backend/app/routers/transactions.py` — `@router.post("")` still accepts multipart fields `file`, `acting_entity_id`, `own_role`, `counterparty_email` and calls `verify_csrf` when account fields are present; account response keys are `{id, lifecycle_version, own_role, acting_entity_id, invitation}`. GET list returns items `{id, state, created_at, buyer_name, seller_name}`; GET detail returns `{id, state, created_at, lifecycle_version, canonical_state, extraction, validator, events, payment}` and enforces 401/403 for account rows.
2. `code/backend/app/routers/invitations.py` — the four routes and error codes in §C5–C8 unchanged; `code/backend/app/schemas/participants.py` — `InvitationCreateResult` has `invite_link`, `InvitationPreview` has `{participant_role, transaction_reference}`.
3. `code/backend/app/routers/participants.py` — routes and codes in §C9–C11 unchanged; `Participant` model fields per `schemas/participants.py`.
4. `code/backend/app/routers/extraction_ops.py` — retry route + codes per §C4.
5. `code/frontend/src/api/client.ts` — `apiRequest`, `ApiClientError`, `setApiActingEntityId` signatures unchanged; `code/frontend/src/routes/AppRoutes.tsx` — route table matches master §1.2.
6. Confirm allowed upload suffixes in `routers/transactions.py` (`_ALLOWED_SUFFIXES`: `.pdf .docx .png .jpg .jpeg .md .txt`).

**Acceptable drift:** added *optional* response fields; new error codes for cases already handled generically; Turkish message text changes. **Stop and report (do not guess):** renamed/removed routes or request fields; changed auth/CSRF requirements; changed response key names; list/detail no longer assignment-scoped.

## C. Verified contract table

Common to all: cookie session auth (`m4t_session`), errors either standard envelope `{code, message, request_id, detail?}` or plain-`HTTPException` string detail (marked ⚠️str — client falls back to generic message, `code = HTTP_<status>`). CSRF = `X-CSRF-Token` required. AE = `X-Acting-Entity-ID` semantics.

### C1 `POST /api/transactions` (account create)
- Auth: session required (when account fields present). CSRF: **yes** (`verify_csrf`). AE: not used for authorization here — authorization is `get_active_membership(user, acting_entity_id from form field)`.
- Content type: `multipart/form-data`. Request fields: `file` (required; suffix ∈ `.pdf .docx .png .jpg .jpeg .md .txt`), `acting_entity_id` (str), `own_role` (`"buyer"|"seller"`), `counterparty_email` (optional str).
- Response 200: `{id: str, lifecycle_version: "account_v2", own_role, acting_entity_id, invitation: null | {invitation_id, participant_role, expires_at, invite_link, notification_delivered: bool}}`. `invite_link` is shown once; treat as secret.
- Lifecycle: creates row `state="uploaded"`, pipeline runs in background → `extracting → awaiting_review|awaiting_approval|rejected`.
- Errors: 400 ⚠️str unsupported suffix · 401 ⚠️str no session · 403 envelope `ACTING_ENTITY_NOT_AUTHORIZED`, `CSRF_TOKEN_INVALID`, `CSRF_ORIGIN_MISMATCH` · 422 envelope `ACCOUNT_CREATE_FIELDS_REQUIRED`, `INVALID_OWN_ROLE` (also FastAPI 422 for missing file).
- Idempotency/retry: **not idempotent** — a network-failed submit must not be blindly retried; UI requires the user to check `/transactions` first (render this instruction on network error).
- Evidence: `routers/transactions.py:364-391`, `tests/test_transaction_ownership_cutover.py`.

### C2 `GET /api/transactions`
- Auth: session (assignment-scoped). CSRF: no. Response 200: `Array<{id, state, created_at, buyer_name: string|null, seller_name: string|null}>` (names come from persisted extraction; null before extraction). Anonymous → 403 ⚠️str. Retry-safe read.
- Evidence: `routers/transactions.py:393-436`.

### C3 `GET /api/transactions/{id}`
- Auth: session; account rows need active assignment. CSRF: no.
- Response 200: `{id, state, created_at, lifecycle_version, canonical_state: string|null (null for account_v2), extraction: RedactedExtraction|null (no tax_id, no source_quote), validator: {status, findings}|null, events: Array<{id, event_type, payload: object|null, source, created_at}>, payment: Array<{other_trx_code, virtual_pos_order_id, status, amount, created_at}>|null (legacy mock_payments only — for account rows typically null)}`.
- Errors: 401 ⚠️str · 403 ⚠️str · 404 ⚠️str. Retry-safe read.
- Evidence: `routers/transactions.py:506-560`.

### C4 `POST /api/transactions/{id}/extraction/retry`
- Auth: session; manager assignment or platform reviewer/admin. CSRF: yes. Request: empty body.
- Response 200: `{transaction_id, job_id, job_status: str|null, attempt_count: int|null, transaction_state: str|null}`.
- Preconditions: `account_v2` AND (state `extracting` OR job ∈ `queued|retry_pending|failed|unknown`).
- Errors: 403 `EXTRACTION_RETRY_FORBIDDEN` · 404 `EXTRACTION_RETRY_NOT_FOUND` · 409 `EXTRACTION_RETRY_IN_PROGRESS` (concurrent claim — safe to refresh, not retry) · 409 `EXTRACTION_RETRY_CONFLICT`.
- Idempotent-ish: atomic claim; losing caller gets 409. No provider side effects (LLM pipeline re-run only).
- Evidence: `routers/extraction_ops.py`, `services/extraction_recovery.py:165-175`, `tests/test_extraction_job_recovery.py`.

### C5 `POST /api/transactions/{id}/invitations`
- Auth: session; **manager assignment** required. CSRF: yes. Request JSON: `{participant_role: "buyer"|"seller", invited_email: string}`.
- Response 200: `{invitation_id, participant_role, expires_at, invite_link}` (`/api/invitations/{raw_token}/accept` shape — display the token part as a frontend link `/invitations/{token}`; extract token = last path segment before `/accept`). TTL 7 days.
- Semantics: creating again for the same role **revokes/supersedes** the previous pending invitation; bound role → 409.
- Errors: 403 `INVITATION_FORBIDDEN` · 409 `INVITATION_ROLE_ALREADY_BOUND` · 401/403 CSRF codes.
- Not idempotent (each call new token) — but replay harm is limited to superseding; still confirm before re-send.
- Evidence: `routers/invitations.py:53-83`, `services/invitations.py:86-171`, `tests/test_invitations_router.py`.

### C6 `GET /api/invitations/{token}/preview`
- Auth: **none**. CSRF: no. Response 200: `{participant_role, transaction_reference}` (8-char prefix; no PII).
- Errors: 404 `INVITATION_NOT_FOUND` for unknown **and** non-pending (accepted/revoked/expired) tokens — message distinguishes but code doesn't; render generic "davet geçersiz/süresi dolmuş/iptal edilmiş olabilir".
- Side-effect free, retry-safe.
- Evidence: `routers/invitations.py:86-91`, `services/invitations.py:174-188`.

### C7 `POST /api/invitations/{token}/accept`
- Auth: session. CSRF: yes. Request JSON: `{legal_entity_id: string}` (must be an entity the user has an active membership in).
- Response 200: full `Participant` `{id, transaction_id, role, legal_entity_id, status, extracted_snapshot, declared_snapshot, confirmed_snapshot, confirmed_at, created_at, updated_at}`.
- Rules: email must match invited email; creator cannot accept own invite; same legal entity cannot hold both roles; single-use atomic bind.
- Errors: 403 `INVITATION_FORBIDDEN` (incl. no membership) / `INVITATION_EMAIL_MISMATCH` · 404 `INVITATION_NOT_FOUND` · 409 `INVITATION_NOT_ACCEPTABLE` (expired/revoked/accepted) / `PARTICIPANT_CONFLICT`.
- Replay: an already-accepted token returns 409 `INVITATION_NOT_ACCEPTABLE`. Do **not** attempt to infer success by matching against the transaction list (the preview reference is only an 8-char prefix — unreliable); render "Bu davet daha önce kullanılmış veya artık geçerli değil." with a link to `/transactions`.
- Evidence: `routers/invitations.py:94-113`, `services/participants.py:203+`, `tests/test_participant_service.py`.

### C8 `POST /api/transactions/{id}/invitations/{invitation_id}/revoke`
- Auth: session; manager or invitation creator. CSRF: yes. Request: empty body. Response 200: `{status: "revoked"}`.
- Errors: 403 `INVITATION_FORBIDDEN` · 404 `INVITATION_NOT_FOUND` · 409 `INVITATION_NOT_REVOCABLE` (already accepted/expired/revoked).
- Evidence: `routers/invitations.py:116-132`.

### C9 `GET /api/transactions/{id}/participants`
- Auth: session; any active assignment. CSRF: no.
- Response 200: `Array<{id, role, status: "invited"|"profile_incomplete"|"ready"|"confirmed", display_name: string|null, confirmed: bool, confirmed_at: string|null}>` — **no PII** (no email/tax/phone).
- Errors: 401 · 403 `TRANSACTION_ACCESS_DENIED`.
- Evidence: `routers/participants.py:93-106`, `tests/test_participants_router.py`.

### C10 `PUT /api/transactions/{id}/participants/me/profile`
- Auth: session (own participant resolved via assignment). CSRF: yes.
- Request JSON: `{snapshot: {name: string, tax_id?: string|null, contact_email?: string|null, contact_phone?: string|null, address?: string|null}}` (`extra="forbid"` — send exactly these keys).
- Response 200: full `Participant` (own — includes snapshots; status becomes `ready`).
- Errors: 404 `PARTICIPANT_NOT_FOUND` (no participant for actor) · 409 `PARTICIPANT_CONFIRMED_LOCKED`.
- Idempotent for same payload. Evidence: `routers/participants.py:109-124`, `services/participants.py:327+`.

### C11 `POST /api/transactions/{id}/participants/me/confirm`
- Auth: session. CSRF: yes. Request: empty body. Response 200: full `Participant` (`status: "confirmed"`, `confirmed_at` set; confirmed snapshot = declared or extracted).
- Precondition: declared or extracted snapshot exists. Side effect: may open a blocking `party_mismatch` review case (visible in PR 2's reviews UI; PR 1 only shows a generic notice that review may be required).
- Errors: 404 `PARTICIPANT_NOT_FOUND` · 409 `PARTICIPANT_CONFIRM_CONFLICT` (already confirmed / nothing to confirm).
- Not repeatable (second call 409 — treat as already-done if participant shows confirmed after refresh).
- Evidence: `routers/participants.py:127-141`, `services/participants.py:363+`.

## D. Blocking and non-blocking gaps

- **Blockers:** none for this PR.
- **Normalizable inconsistencies:**
  - Mixed error body styles (envelope vs ⚠️str) — normalize via `ApiClientError.kind`/`status`; branch on `code` only for envelope endpoints (tables above mark which).
  - No invitation list endpoint (master §14.1 B4): the parties page keeps the **last create response** in page state (id, expires_at, link) and renders participant `status` as source of truth. After page reload the pending invitation can no longer be revoked from the UI (id unknown) — render Turkish hint: "Bekleyen daveti iptal etmek için aynı role yeni davet gönderin (eski davet otomatik geçersiz olur)". This is contract-accurate supersede behavior.
  - `payment` field in detail is legacy-only — render nothing for account rows when `null`.
- **Unsupported states needing clear UI:** `rejected` state (validator REJECT) → overview shows danger badge + explanation, no commands; `awaiting_review` → notice that manual review is pending (full review UI arrives in PR 2); reload-lost declared profile (B9, master §14.1) → overwrite-guard warning + confirm dialog per §H (recommended backend follow-up: `GET .../participants/me`).
- **Assumptions the implementer must never make:** do not derive who is manager/approver from heuristics — attempt commands and render 403 results, or use only own mutation responses; do not compute lifecycle transitions client-side; do not synthesize buyer/seller names when extraction is null.

## E. Route changes

- Created: `/transactions` (list), `/transactions/new` (RequireAuth), `/transactions/:transactionId` (RequireAuth; shell) with children `index → <Navigate to="overview" replace>`, `overview`, `parties`; `/invitations/:token` (public — preview visible logged-out; accept panel requires auth). **Login behavior (single, security-first rule):** the token is never carried into router state, query params, or any other URL; the logged-out page shows a plain link to `/login` plus the instruction "Giriş yaptıktan sonra bu davet bağlantısını yeniden açın." (§H row 6 follows this same rule).
- Extended: `AppShell` nav gains "İşlemler" link (`/transactions`, visible when `user`); HomePage gets a CTA link to `/transactions` for logged-in users (minimal text change only).
- Redirects: `/transactions/:id` index → `overview`. After accept success → `navigate(\`/transactions/${participant.transaction_id}/parties\`, { replace: true })` (token leaves history).
- Guards: RequireAuth as listed; no other guards (backend owns authorization).
- Token cleanup: `/invitations/:token` never propagates token into other links; no logging.
- Route-level loading/failure: shell shows `LoadingPanel` until detail read resolves; detail 404 → in-shell `EmptyState` "İşlem bulunamadı"; 401 handled by redirect handler; 403 → in-shell permission panel with "Erişiminiz yok" + link to `/transactions`.

## F. Exact TypeScript types

`src/types/transactions.ts` (new):
```ts
export type LifecycleVersion = "legacy_v1" | "account_v2";
export type AccountState =
  | "preparation" | "uploaded" | "extracting" | "awaiting_review"
  | "awaiting_approval" | "awaiting_ratification" | "funding_pending"
  | "active" | "settled" | "rejected" | "cancelled" | (string & {});
export interface TransactionListItem { id: string; state: AccountState; created_at: string; buyer_name: string | null; seller_name: string | null; }
export interface ExtractionPartyView { name: string; }              // redacted: no tax_id rendered even if present
export interface ExtractionGoods { name: string; quantity: number; unit: string; }
export interface ExtractionPaymentRule { milestone: string; trigger: string; percentage: number; required_evidence: string[]; confidence: number; }
export interface RedactedExtraction {
  contract_id: string;
  parties: { buyer: ExtractionPartyView; seller: ExtractionPartyView };
  commercial_terms: { currency: string; total_amount: number; goods: ExtractionGoods[]; delivery_deadline: string | null };
  payment_rules: ExtractionPaymentRule[];
  risk_flags: string[];
  needs_manual_review: boolean;
}
export interface ValidatorFinding { code: string; severity: string; message?: string; }
export interface ValidatorReport { status: "PASS" | "NEEDS_REVIEW" | "REJECT" | (string & {}) | null; findings: ValidatorFinding[] | null; }
export interface TransactionEvent { id: number; event_type: string; payload: Record<string, unknown> | null; source: string; created_at: string; }
export interface LegacyPaymentRow { other_trx_code: string; virtual_pos_order_id: string | null; status: string; amount: number; created_at: string; }
export interface TransactionDetail {
  id: string; state: AccountState; created_at: string;
  lifecycle_version: LifecycleVersion; canonical_state: string | null;
  extraction: RedactedExtraction | null; validator: ValidatorReport | null;
  events: TransactionEvent[]; payment: LegacyPaymentRow[] | null;
}
export interface CreatedInvitationView { invitation_id: string; participant_role: string; expires_at: string; invite_link: string; notification_delivered?: boolean; }
export interface CreateTransactionResponse { id: string; lifecycle_version: "account_v2"; own_role: "buyer" | "seller"; acting_entity_id: string; invitation: CreatedInvitationView | null; }
export interface ExtractionRetryResponse { transaction_id: string; job_id: string; job_status: string | null; attempt_count: number | null; transaction_state: string | null; }
```

`src/types/participants.ts` (new):
```ts
export type ParticipantRole = "buyer" | "seller";
export type ParticipantStatus = "invited" | "profile_incomplete" | "ready" | "confirmed" | (string & {});
export interface PartyProfileSnapshot { name: string; tax_id?: string | null; contact_email?: string | null; contact_phone?: string | null; address?: string | null; }
export interface Participant {
  id: string; transaction_id: string; role: ParticipantRole; legal_entity_id: string | null;
  status: ParticipantStatus;
  extracted_snapshot: PartyProfileSnapshot | null; declared_snapshot: PartyProfileSnapshot | null; confirmed_snapshot: PartyProfileSnapshot | null;
  confirmed_at: string | null; created_at: string; updated_at: string;
}
export interface ParticipantPublicView { id: string; role: ParticipantRole; status: ParticipantStatus; display_name: string | null; confirmed: boolean; confirmed_at: string | null; }
export interface InvitationCreateRequest { participant_role: ParticipantRole; invited_email: string; }
export interface InvitationCreateResult { invitation_id: string; participant_role: ParticipantRole; expires_at: string; invite_link: string; }
export interface InvitationPreview { participant_role: ParticipantRole; transaction_reference: string; }
export interface InvitationAcceptRequest { legal_entity_id: string; }
export interface ProfileUpdateRequest { snapshot: PartyProfileSnapshot; }
```

Helper (pure, testable) in `src/lib/inviteLink.ts`: `extractInvitationToken(inviteLink: string): string | null` — parses `/api/invitations/{token}/accept`; `frontendInvitationPath(token: string): string` → `/invitations/${token}`.

## G. Exact API functions

`src/api/transactions.ts` (new):
| Function | Method & URL | Req type | Resp type | csrf | notes |
|---|---|---|---|---|---|
| `createTransaction(form: FormData)` | POST `/transactions` | FormData (`file`,`acting_entity_id`,`own_role`,`counterparty_email?`) | `CreateTransactionResponse` | true | `redirectOnError:false`; expected errors C1 |
| `listTransactions()` | GET `/transactions` | — | `TransactionListItem[]` | false | default redirect |
| `getTransaction(id: string)` | GET `/transactions/${id}` | — | `TransactionDetail` | false | `redirectOnError:false` (shell renders inline states) |
| `retryExtraction(id: string)` | POST `/transactions/${id}/extraction/retry` | — | `ExtractionRetryResponse` | true | `redirectOnError:false` |

`src/api/invitations.ts` (new):
| Function | Method & URL | Req | Resp | csrf |
|---|---|---|---|---|
| `createInvitation(transactionId, body: InvitationCreateRequest)` | POST `/transactions/${transactionId}/invitations` | JSON | `InvitationCreateResult` | true |
| `previewInvitation(token)` | GET `/invitations/${encodeURIComponent(token)}/preview` | — | `InvitationPreview` | false (`redirectOnError:false`) |
| `acceptInvitation(token, body: InvitationAcceptRequest)` | POST `/invitations/${encodeURIComponent(token)}/accept` | JSON | `Participant` | true |
| `revokeInvitation(transactionId, invitationId)` | POST `/transactions/${transactionId}/invitations/${invitationId}/revoke` | — | `{status: string}` | true |

`src/api/participants.ts` (new):
| Function | Method & URL | Req | Resp | csrf |
|---|---|---|---|---|
| `listParticipants(transactionId)` | GET `/transactions/${transactionId}/participants` | — | `ParticipantPublicView[]` | false |
| `updateMyProfile(transactionId, body: ProfileUpdateRequest)` | PUT `/transactions/${transactionId}/participants/me/profile` | JSON | `Participant` | true |
| `confirmMyProfile(transactionId)` | POST `/transactions/${transactionId}/participants/me/confirm` | — | `Participant` | true |

All mutations: `redirectOnError: false`. Acting-entity header is automatic (client); no function passes tokens except the two invitation-token functions.

## H. Page and component tree

Shared components: exactly as master §5 (`TransactionShell`, `SectionNav`, `StatusBadge` + `lib/statusMaps.ts`, `Timeline`, `ConfirmDialog`, `EmptyState`, `KeyValueGrid`, `ResponsiveTable`, `lib/useAsyncData.ts`, `lib/usePolling.ts`, `lib/format.ts`). Status maps created now: `transactionStateMap` (uploaded/extracting→info "İşleniyor"; awaiting_review→warning "Manuel inceleme bekliyor"; awaiting_approval→info "Onay hazırlığı"; awaiting_ratification→info "Taraf onayı bekleniyor"; funding_pending→warning "Fonlama bekliyor"; active→success "Aktif"; settled→success "Tamamlandı"; rejected→danger "Reddedildi"; cancelled→neutral "İptal"; unknown→neutral raw value), `participantStatusMap`, `validatorStatusMap`.

| File | Component | Responsibility / key behaviors |
|---|---|---|
| `pages/transactions/TransactionListPage.tsx` | `TransactionListPage` | Reads `listTransactions()` via `useAsyncData`. Loading `LoadingPanel`; error `RetryPanel`; empty `EmptyState` with CTA to `/transactions/new`. Renders `ResponsiveTable` ≥640px (columns: kısa ID linkli, durum `StatusBadge`, alıcı, satıcı, tarih) and stacked link-cards <640px. No permission state (403 list only when anonymous → redirect handler). |
| `pages/transactions/TransactionCreatePage.tsx` | `TransactionCreatePage` | Form: file input (accept=".pdf,.docx,.png,.jpg,.jpeg,.md,.txt"), role radio (buyer/seller, Turkish labels), optional counterparty email, read-only display of selected acting entity (from `useEntities`; if none → form disabled with Notice "Önce işlem yapılacak entity'yi seçin"). Submit builds FormData; success → if `invitation` present, show one-time panel (link `/invitations/{token}` via `extractInvitationToken`, copy button, secret warning) with "İşleme git" button; else navigate to `/transactions/{id}/overview`. Client-side check only for file presence; suffix errors come from backend 400. Network-failure notice per C1. |
| `components/TransactionShell.tsx` | `TransactionShell` | Owns `getTransaction(id)` read; heading = short id + `StatusBadge(state)` + created_at; `SectionNav` sections `[overview, parties]` (registry const in this file); outlet context `{detail, refresh, loading, error}`; 404/403/error panels per §E. |
| `pages/transactions/TransactionOverviewPage.tsx` | `TransactionOverviewPage` | Uses shell context only (no own read). Blocks: state explanation Notice (per state map); extraction summary (`KeyValueGrid`: contract_id, taraflar, tutar `formatAmountMinor`? — **no**: `total_amount` is major units from extraction, render with `Intl.NumberFormat` + currency code, no /100), goods table, payment_rules table (milestone, trigger, %, required_evidence, confidence), risk_flags list, needs_manual_review notice; validator block (status badge + findings list code+severity+message); events `Timeline` (event_type→Turkish label map `lib/eventLabels.ts`, unknown types render raw type, payload NOT dumped — selected safe scalar fields only: status/finding_codes/counts); extraction-retry `CommandPanel` visible when `state ∈ {uploaded, extracting}` for >60s heuristic **not used** — instead always render the button when state=="extracting", with helper text; confirm dialog; result notice with job_status/attempt_count; 403 → Notice "Yalnız işlem yöneticisi tetikleyebilir". Polling: `usePolling(shell.refresh, {active: state==="uploaded"||state==="extracting", intervalMs: 4000})`. |
| `pages/transactions/TransactionPartiesPage.tsx` | `TransactionPartiesPage` | Own read: `listParticipants`. Three blocks: (1) participants table (role, display_name, status badge, confirmed_at); (2) invitation panel: role select limited to roles whose participant is `status==="invited" && !confirmed`, email input, submit → success stores `InvitationCreateResult` in state and renders one-time link + expires_at + revoke button (`ConfirmDialog`); revoke success → refresh participants + clear stored invitation; 409 `INVITATION_ROLE_ALREADY_BOUND` → Notice; supersede hint per §D; (3) my-profile panel: fields name/tax_id/contact_email/contact_phone/address prefilled from last own `Participant` response if present in page state. **Overwrite guard (limitation B9, master §14.1 — no `GET participants/me` exists):** after a reload the declared snapshot cannot be re-read; when the public list shows my participant `status ∈ {ready, confirmed-pending}` but no local snapshot is held, the form renders collapsed behind a warning Notice — "Daha önce kaydedilmiş profil bilgileriniz görüntülenemiyor (API sınırı). Formu göndermek önceki TÜM alanların üzerine yazar." — and submit additionally requires a `ConfirmDialog`. Own explicitly-entered `tax_id` appears only inside this form (master §9.6 tax-id rule). PUT submit → success Notice + store returned participant; Confirm button (`ConfirmDialog`, text explains snapshot freezes) → success → refresh participants + shell.refresh (state may not change; review case may open → info Notice "Profil onaylandı; olası uyuşmazlık incelemesi kural bölümünde görünecek"). 404 `PARTICIPANT_NOT_FOUND` on PUT/confirm → panel replaced with Notice "Bu işlemde katılımcı kaydınız yok (görüntüleyici olabilirsiniz)". 409 `PARTICIPANT_CONFIRMED_LOCKED`/`PARTICIPANT_CONFIRM_CONFLICT` → Notice + refresh. |
| `pages/InvitationPage.tsx` | `InvitationPage` | Route `/invitations/:token`. Read `previewInvitation` (`useAsyncData`). 404 → `EmptyState` "Davet geçersiz, süresi dolmuş veya iptal edilmiş olabilir." Preview OK → card: rol (Turkish), işlem referansı. If not logged in → CTA to `/login` (after login user returns manually; acceptable, note in copy) — do NOT auto-redirect with token in state to avoid token spread; keep it simple: text "Giriş yaptıktan sonra bu bağlantıyı yeniden açın." If logged in → entity select (from `useEntities`; empty → link `/entities/new`), accept button → `acceptInvitation` → success navigate `replace` to `/transactions/{transaction_id}/parties`. Error handling per C7 with specific Turkish copy per code (`INVITATION_EMAIL_MISMATCH`: "Bu davet başka bir e-posta adresine gönderilmiş."; `INVITATION_NOT_ACCEPTABLE`: "Bu davet daha önce kullanılmış veya artık geçerli değil." + link to `/transactions`; `PARTICIPANT_CONFLICT`: "Bu rol zaten bağlanmış veya entity çakışması var."). |
| `pages/index.ts` | — | re-export new pages. |
| `routes/AppRoutes.tsx` | — | add routes per §E. |

Responsive/accessibility: per master §10 (list page cards <640px; dialogs; focus rules; badges with text).

## I. Data loading and mutation refresh

| Page | Initial reads | Order | Refresh triggers | Mutation success | Mutation failure | Stale/cancel |
|---|---|---|---|---|---|---|
| List | `listTransactions` | single | manual "Yenile" button + on mount | — | RetryPanel | useAsyncData guard |
| Create | none (entities from context) | — | — | navigate or invite panel | FormError inline | n/a |
| Shell | `getTransaction` | single | `refresh()` from children; polling per overview | — | in-shell panels | guard |
| Overview | none (context) | — | polling while uploaded/extracting | retry → `shell.refresh()` | inline Notice | polling stops on unmount |
| Parties | `listParticipants` (parallel with nothing) | single | after create/revoke/PUT/confirm: `refreshParticipants()`; after confirm also `shell.refresh()` | per §H | inline per-panel FormError | guard |
| Invitation | `previewInvitation` | single | on token change | accept → navigate replace | inline | guard |

No polling elsewhere; no optimistic state anywhere.

## J. Lifecycle and action matrix (account_v2)

| State | Badge (tone) | Reads shown | Commands available | Commands disabled + reason shown |
|---|---|---|---|---|
| `uploaded`/`extracting` | "İşleniyor" (info) | events; no extraction yet | extraction retry (extracting) | invitation/profile allowed (backend permits); ratification-era commands absent (PR 2) |
| `awaiting_review` | warning | extraction, validator NEEDS_REVIEW findings | invitation, profile, confirm | notice: "Manuel inceleme tamamlanana kadar onay paketi oluşturulamaz" (informational only in PR 1) |
| `awaiting_approval` | info | extraction, validator PASS | invitation, profile, confirm | — |
| `awaiting_ratification` | info | same | same | — |
| `funding_pending` | warning | same + events | none new in PR 1 | invitation for bound role → 409 rendered |
| `active` | success | events grow (evidence etc. PR 3) | — | — |
| `settled` | success | full timeline | none | all mutations → backend 409s rendered generically |
| `rejected` | danger | validator REJECT findings | none | explanatory notice, no commands |
| unknown state | neutral raw | whatever detail returns | none | generic notice |

Backend-owned data never derived: state transitions, validator outcome, who may invite/confirm, review-case creation.

## K. Execution task packets

#### Task 1 — Shared lib: hooks, format, event labels
**Goal** `useAsyncData`, `usePolling`, `format.ts`, `eventLabels.ts`, `inviteLink.ts` exist and are unit-tested.
**Depends on** —
**Files to create** `src/lib/useAsyncData.ts`, `src/lib/usePolling.ts`, `src/lib/format.ts`, `src/lib/eventLabels.ts`, `src/lib/inviteLink.ts`, `src/lib/format.test.ts`, `src/lib/inviteLink.test.ts`, `src/lib/eventLabels.test.ts`
**Files to modify** —
**Required changes** implement per master §5/§6: `useAsyncData<T>(fetcher, deps)` returning `{data, loading, error: ApiClientError|null, refresh}` with stale guard; `usePolling(cb, {active, intervalMs})` with cleanup; `formatDateTime`, `formatAmountMinor`, `formatPercentBps` with invalid-input fallbacks; `eventLabels: Record<string,string>` covering the event types listed in ARCHITECTURE §4.3 plus `funding_required`, `funding_units_pool_created`, `funding_units_approved`, `transaction_settled`, `rule_set_revised`; token helpers per §F.
**Must not change** `api/client.ts`, contexts.
**Tests to add or update** the three `.test.ts` files: format edge cases (invalid ISO → "—", unknown currency), token extraction (valid link, garbage, missing segments), label fallback.
**Verification commands** `cd code/frontend && npm run lint && npm run typecheck && npm run test`
**Done when** all green; no page imports yet.

#### Task 2 — Shared components
**Goal** `StatusBadge`, `SectionNav`, `Timeline`, `ConfirmDialog`, `ResponsiveTable`, `EmptyState`, `KeyValueGrid`, `statusMaps.ts` exist.
**Depends on** Task 1
**Files to create** `src/components/StatusBadge.tsx`, `src/components/SectionNav.tsx`, `src/components/Timeline.tsx`, `src/components/ConfirmDialog.tsx`, `src/components/ResponsiveTable.tsx`, `src/lib/statusMaps.ts`, `src/lib/statusMaps.test.ts`
**Files to modify** `src/components/Feedback.tsx` (add `EmptyState`, `KeyValueGrid` — do not alter existing exports)
**Required changes** props exactly per master §5; a11y per master §10 (dialog focus trap with `useRef`+keydown, `role="dialog"`, `aria-modal`; nav `aria-current`); Tailwind classes consistent with 8A style (rounded-2xl/3xl, white/10 borders, slate palette).
**Must not change** existing Feedback exports, `pages/shared.tsx`.
**Tests to add or update** `statusMaps.test.ts`: every declared state key returns `{label, tone}`; unknown key handling helper `resolveStatus(map, value)` returns neutral raw fallback.
**Verification commands** `npm run lint && npm run typecheck && npm run test && npm run build`
**Done when** build passes with components exported (temporarily unused is fine — keep exports referenced from an `index` or use them in Task 4 before lint complains; if `eslint` flags unused, wire them in the same commit as Task 4).

#### Task 3 — Types and API modules
**Goal** typed domain + API layer for transactions/invitations/participants.
**Depends on** Task 1
**Files to create** `src/types/transactions.ts`, `src/types/participants.ts`, `src/api/transactions.ts`, `src/api/invitations.ts`, `src/api/participants.ts`, `src/api/transactions.test.ts`
**Files to modify** —
**Required changes** exactly §F and §G. `createTransaction` must not set Content-Type (client passes FormData through).
**Must not change** `src/api/client.ts`, `src/types/api.ts` existing content.
**Tests to add or update** `api/transactions.test.ts`: mock `fetch` (pattern from `client.test.ts`) asserting URL/method/credentials/CSRF header presence for `createTransaction` (with cookie set) and JSON parse of list/detail; error envelope → `ApiClientError.code`.
**Verification commands** `npm run lint && npm run typecheck && npm run test`
**Done when** green.

#### Task 4 — Transaction list + create pages, routes
**Goal** `/transactions`, `/transactions/new` functional.
**Depends on** Tasks 2, 3
**Files to create** `src/pages/transactions/TransactionListPage.tsx`, `src/pages/transactions/TransactionCreatePage.tsx`
**Files to modify** `src/routes/AppRoutes.tsx`, `src/pages/index.ts`, `src/components/AppShell.tsx` (nav link "İşlemler"), `src/pages/HomePage.tsx` (CTA link only)
**Required changes** per §H rows 1–2 and §E.
**Must not change** existing routes/pages beyond stated files; `EntityContext`.
**Tests to add or update** extract pure helpers where logic exists: `src/pages/transactions/createTransactionForm.ts` (builds FormData from typed input; validates role member of union; returns error string for missing file) + `createTransactionForm.test.ts`.
**Verification commands** `npm run lint && npm run typecheck && npm run test && npm run build`
**Done when** manual dev-server check: list renders (empty state), create form submits against running backend (or is verified in §M smoke later); CI-style commands green.

#### Task 5 — TransactionShell + overview section
**Goal** detail shell with overview incl. polling and extraction retry.
**Depends on** Task 4
**Files to create** `src/components/TransactionShell.tsx`, `src/pages/transactions/TransactionOverviewPage.tsx`, `src/pages/transactions/overviewProjection.ts`, `src/pages/transactions/overviewProjection.test.ts`
**Files to modify** `src/routes/AppRoutes.tsx` (nested routes), `src/pages/index.ts`
**Required changes** per §H rows 3–4; `overviewProjection.ts` holds pure helpers: `stateNotice(state)`, `safeEventItems(events)` (maps `TransactionEvent[]` → `Timeline` items using `eventLabels`, extracting only allowlisted payload scalars: `status`, `finding_codes`, `funding_unit_count`, `milestone_count`, `action`, `manual_review_required`), `shouldPoll(state)`.
**Must not change** section registry beyond `["overview","parties"]` placeholder for parties (route added Task 6; nav entry may exist pointing to a stub only if Task 6 lands in same PR — it does).
**Tests to add or update** `overviewProjection.test.ts`: event mapping drops non-allowlisted payload keys (feed a payload containing `token`/`raw` keys and assert absence), `shouldPoll` truth table.
**Verification commands** `npm run lint && npm run typecheck && npm run test && npm run build`
**Done when** green; navigating to a detail id renders shell states (loading/404/data).

#### Task 6 — Parties section
**Goal** participants table + invitation panel + my-profile/confirm.
**Depends on** Task 5
**Files to create** `src/pages/transactions/TransactionPartiesPage.tsx`, `src/pages/transactions/partiesLogic.ts`, `src/pages/transactions/partiesLogic.test.ts`
**Files to modify** `src/routes/AppRoutes.tsx`, `src/pages/index.ts`
**Required changes** per §H row 5. `partiesLogic.ts` pure helpers: `invitableRoles(participants)` (roles with `status==="invited" && !confirmed`), `profileSnapshotFromForm(fields)` (trims, empty→null, returns `PartyProfileSnapshot`), `inviteErrorMessage(code)` mapping.
**Must not change** shell context shape.
**Tests to add or update** `partiesLogic.test.ts`: invitable roles across status combinations; snapshot normalization; error-code → Turkish message mapping incl. unknown code fallback.
**Verification commands** `npm run lint && npm run typecheck && npm run test && npm run build`
**Done when** green.

#### Task 7 — Invitation preview/accept page
**Goal** `/invitations/:token` full flow.
**Depends on** Task 3 (and Task 2 components)
**Files to create** `src/pages/InvitationPage.tsx`, `src/pages/invitationLogic.ts`, `src/pages/invitationLogic.test.ts`
**Files to modify** `src/routes/AppRoutes.tsx`, `src/pages/index.ts`
**Required changes** per §H row 6; `invitationLogic.ts`: `acceptErrorMessage(code, status)` per C7 incl. generic fallback; `previewUnavailableMessage()`.
**Must not change** auth flow, login page.
**Tests to add or update** `invitationLogic.test.ts`: message mapping for every C7 code + unknown.
**Verification commands** `npm run lint && npm run typecheck && npm run test && npm run build`
**Done when** green.

#### Task 8 — DOM/component test layer
**Goal** behavior that pure helpers cannot verify is covered by component tests (master §1.5 revised test strategy).
**Depends on** Tasks 2, 5, 6, 7
**Files to create** `src/components/ConfirmDialog.test.tsx`, `src/components/SectionNav.test.tsx`, `src/routes/AppRoutes.test.tsx`, `src/pages/InvitationPage.test.tsx`, `src/lib/useAsyncData.test.tsx` (replaces the node-only stale-guard test if it proved artificial)
**Files to modify** `package.json` (devDependencies ONLY: `jsdom`, `@testing-library/react`, `@testing-library/user-event`; no runtime deps), `vitest.config.ts` (add `src/**/*.test.tsx` to include; keep default `environment: "node"`; `.test.tsx` files opt into jsdom via `// @vitest-environment jsdom` first-line comment)
**Required changes** ConfirmDialog: focus trapped, `Esc` cancels, `requireText` gates confirm, focus returns to trigger; SectionNav: `aria-current` on active link; AppRoutes: `/transactions/:id` index redirects to `overview`, RequireAuth redirects anonymous to `/session-required` (mock AuthContext); InvitationPage: logged-out shows login link WITHOUT token anywhere in `document.body` HTML or the login href; useAsyncData: stale resolution after deps change is not applied (renderHook).
**Must not change** existing `.test.ts` node tests; CI workflow (vitest picks up new include automatically).
**Tests to add or update** the five files above.
**Verification commands** `npm run lint && npm run typecheck && npm run test && npm run build`
**Done when** all green including the new `.tsx` tests.

#### Task 9 — Docs, doc-sync and final pass
**Goal** README + ARCHITECTURE route list updated; whole suite green.
**Depends on** Tasks 1–8
**Files to create** —
**Files to modify** `code/frontend/README.md` (new routes + smoke steps summary), `ARCHITECTURE.md` (§1 bottom frontend route list: add the PR 1 routes, mark legacy `/t/:id/*` unchanged) — **only** the frontend route sentence/paragraph; this plan file (status block, moved to `plans/done/` at merge per AGENTS protocol — the move itself happens at merge, not in this PR if the team prefers; follow AGENTS).
**Required changes** doc text only (README also documents the new dev-only test dependencies and the `.test.tsx`/jsdom convention).
**Must not change** any other ARCHITECTURE section; AGENTS.md.
**Tests to add or update** —
**Verification commands** §N full list.
**Done when** §N all green and `git status --short` shows only intended files.

## L. Test matrix

All tests are vitest node tests over pure helpers / API modules with mocked `fetch` (established 8A pattern — no jsdom).

| Scenario | Test location |
|---|---|
| API contract parsing: list/detail/create/retry happy paths (typed) | `api/transactions.test.ts` |
| createTransaction sends multipart w/o manual Content-Type, with CSRF header | `api/transactions.test.ts` |
| Error envelope → code/kind mapping; ⚠️str 403 detail → generic message, `HTTP_403` | `api/transactions.test.ts` (reuses client behavior; assert via mocked responses) |
| 401 on detail → `session_required` kind | `api/transactions.test.ts` |
| 404 preview → not_found kind, inline message helper | `invitationLogic.test.ts` |
| 409 codes: `INVITATION_ROLE_ALREADY_BOUND`, `INVITATION_NOT_ACCEPTABLE`, `PARTICIPANT_CONFLICT`, `PARTICIPANT_CONFIRMED_LOCKED`, `PARTICIPANT_CONFIRM_CONFLICT`, `EXTRACTION_RETRY_IN_PROGRESS` → distinct Turkish copy | `partiesLogic.test.ts`, `invitationLogic.test.ts`, `overviewProjection.test.ts` |
| 422 `ACCOUNT_CREATE_FIELDS_REQUIRED`/`INVALID_OWN_ROLE` mapping | `createTransactionForm.test.ts` |
| Network failure on create → non-retry warning copy | `createTransactionForm.test.ts` |
| Invalid JSON response → `invalid_response` (client already covers; regression via api test) | `api/transactions.test.ts` |
| Retry semantics: extraction retry response projection; 409 → refresh-not-retry copy | `overviewProjection.test.ts` |
| Superseded/stale: new invitation supersedes — `invitableRoles` still offers role while unbound | `partiesLogic.test.ts` |
| Authorization-dependent visibility: profile panel hidden on 404 PARTICIPANT_NOT_FOUND (helper returns render mode) | `partiesLogic.test.ts` |
| Lifecycle rendering: `stateNotice` for every state incl. unknown; `shouldPoll` table | `overviewProjection.test.ts`, `statusMaps.test.ts` |
| Token states: extract/format helpers never log; `frontendInvitationPath` shape | `inviteLink.test.ts` |
| Sensitive-data redaction: event payload allowlist drops `token`/`raw`/`markdown` keys | `overviewProjection.test.ts` |
| Loading/empty: `useAsyncData` stale-guard (resolve after deps change is ignored, via renderHook) | `src/lib/useAsyncData.test.tsx` |
| DOM behavior: dialog focus trap/Esc/requireText; nav aria-current; index redirect; RequireAuth redirect; invitation page never leaks token into DOM/login href | Task 8 `.test.tsx` files |

## M. Manual browser smoke (do not claim performed unless actually run)

- **Prerequisites:** `code/.env` from `backend/.env.example` with `APP_ENCRYPTION_KEY`, `APP_HMAC_KEY`, `SESSION_COOKIE_SECURE=false`; Python venv ready; Node 22.
- **Backend:** `cd code && ./.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000` (Windows: `.venv\Scripts\python -m uvicorn ...`).
- **Seed:** `cd code && ./.venv/bin/python scripts/seed_demo_users.py` (Berke/Yusuf + ABC A.Ş./XYZ Ltd.).
- **Frontend:** `cd code/frontend && npm install && npm run dev` → `http://127.0.0.1:5173`.
- **Actions & expected observations:**
  1. Login as Berke, select ABC A.Ş. → `/transactions` shows empty state.
  2. `/transactions/new`: upload a small `.md` contract fixture, role buyer, counterparty = Yusuf's seed email → success panel shows one-time `/invitations/{token}` link; copy it.
  3. Detail overview: badge cycles `uploaded/extracting` (polling visible in network tab, 4 s) → `awaiting_approval` (fake extraction) with extraction summary + validator PASS + timeline events.
  4. Parties: two participants (buyer bound, seller `invited`); invitation panel shows stored invite with revoke; fill+save my profile → status `ready`; confirm → `confirmed`, further edits blocked with Turkish 409 message.
  5. Second browser/profile: open invite link logged-out → preview only; login as Yusuf, select XYZ Ltd., accept → lands on parties; URL token gone from address bar after redirect.
  6. Re-open same invite link → "davet geçersiz…" (409/404 path).
  7. Create a second invitation for seller before accept → old link 404s on preview (superseded).
- **Failure checks:** stop backend → list shows network RetryPanel, create shows non-retry warning; wrong-file `.exe` → backend 400 rendered as generic validation message.
- **Security checks:** localStorage contains only `m4t_acting_entity_id`; no request except preview/accept carries the invitation token; `document.cookie` shows only `m4t_csrf` readable; no `tax_id` or `source_quote` anywhere in DOM (search devtools).
- **Responsive checks:** 375 px width — list becomes cards, nav wraps, dialogs usable; keyboard-only pass over create + accept flows.

## N. Final verification commands

```bash
cd code/frontend
npm ci                     # or npm install locally
npm run lint
npm run typecheck
npm run test               # full frontend suite
npm run build
# targeted backend contract tests (unchanged backend — must stay green):
cd .. && ./.venv/bin/python -m pytest tests/test_transaction_ownership_cutover.py tests/test_invitations_router.py tests/test_participants_router.py tests/test_extraction_job_recovery.py -q
git diff --check
git status --short         # only files in §O
```

## O. Expected file manifest

Created: `src/lib/{useAsyncData,usePolling,format,eventLabels,inviteLink,statusMaps}.ts` + `src/lib/{format,inviteLink,eventLabels,statusMaps}.test.ts` + `src/lib/useAsyncData.test.tsx` · `src/components/{StatusBadge,SectionNav,Timeline,ConfirmDialog,ResponsiveTable,TransactionShell}.tsx` + `src/components/{ConfirmDialog,SectionNav}.test.tsx` · `src/routes/AppRoutes.test.tsx` · `src/types/{transactions,participants}.ts` · `src/api/{transactions,invitations,participants}.ts` + `src/api/transactions.test.ts` · `src/pages/transactions/{TransactionListPage,TransactionCreatePage,TransactionOverviewPage,TransactionPartiesPage}.tsx` + `{createTransactionForm,overviewProjection,partiesLogic}.ts` + matching `.test.ts` · `src/pages/InvitationPage.tsx` + `src/pages/InvitationPage.test.tsx` + `src/pages/invitationLogic.ts` + test.
Modified: `src/routes/AppRoutes.tsx`, `src/pages/index.ts`, `src/components/{AppShell,Feedback}.tsx`, `src/pages/HomePage.tsx`, `package.json` + `package-lock.json` (dev-only test deps), `vitest.config.ts` (`.test.tsx` include), `code/frontend/README.md`, `ARCHITECTURE.md` (frontend route list only), this plan's status block.
Uncertainty: exact split of pure-helper files may vary ±1 file if lint prefers co-location; nothing else.

## P. Binary acceptance criteria

1. `npm run lint`, `typecheck`, `test`, `build` all exit 0 in `code/frontend`.
2. Backend suite untouched: `git diff --stat -- code/backend code/tests` is empty; targeted backend tests in §N pass.
3. Routes `/transactions`, `/transactions/new`, `/transactions/:id/overview`, `/transactions/:id/parties`, `/invitations/:token` exist and render without console errors against a running backend.
4. Every mutation in §C sends `X-CSRF-Token`; verified by api tests.
5. Invitation token appears in no request URL other than preview/accept (api tests + smoke).
6. All §L rows have at least one passing test.
7. Unknown transaction state renders neutral badge, not a crash (test).
8. No new **runtime** dependency in `package.json`; devDependency additions limited to exactly `jsdom`, `@testing-library/react`, `@testing-library/user-event`.
9. DOM tests of Task 8 pass (dialog focus trap, requireText gate, index redirect, RequireAuth redirect, invitation-token DOM leak check).
10. Reload-overwrite guard on the profile form is present (warning + confirm dialog when local snapshot absent but participant status is `ready`).
11. Manual smoke §M executed and reported honestly (checklist with pass/fail per line) in the PR description.

## Q. Implementation handoff prompt

```
You are implementing frontend PR 1 of 3 for M4Trust. Repository: gencberke/M4Trust-B2B-deal-management. Base branch: program/domain-evolution-v2, or master only if `git merge-base --is-ancestor ebf6dc7 master` succeeds (the base MUST contain the PR #67 frontend foundation).
1. Read AGENTS.md, then plans/ready/08_frontend_completion_master_plan.md, then plans/ready/08b1_frontend_deal_core.md fully.
2. Run the §B contract-drift preflight (open only the named files). If any "stop" condition matches, STOP and report the drift instead of guessing.
3. Create branch feat/frontend-deal-core from the verified base.
4. Execute task packets §K Task 1 → Task 9 strictly in order; add the specified tests with each packet; keep UI strings Turkish. The only allowed package.json change is the dev-only test dependencies in Task 8.
5. Never modify code/backend/**, code/tests/**, api/client.ts, AuthContext, EntityContext, or CI workflows.
6. Group work into exactly the 3 commits listed in §A.
7. Run all §N verification commands; all must pass; git status --short must show only §O files.
8. Push the branch and open a DRAFT PR against the verified base branch, titled per §A, PR body = scope summary + §P checklist + honest §M smoke report (state explicitly if smoke was not run).
```

**Readiness status: `READY_TO_IMPLEMENT`**
