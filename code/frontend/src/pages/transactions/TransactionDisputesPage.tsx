import { useState } from "react";

import { toApiClientError } from "../../api/client";
import { listDisputes, openDispute, submitDisputeAction } from "../../api/disputes";
import { getEvidenceBundle, getMilestones } from "../../api/evidence";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState, LoadingPanel, Notice, RetryPanel } from "../../components/Feedback";
import { useTransactionShell } from "../../components/TransactionShell";
import { useAsyncData } from "../../lib/useAsyncData";
import type { DisputeActionInput, DisputeView } from "../../types/disputes";
import { buttonClass, inputClass, secondaryButtonClass } from "../shared";
import { DISPUTE_ACTIONS, disputeErrorMessage } from "./disputes/disputesLogic";

type DisputeAction = (typeof DISPUTE_ACTIONS)[number];

function DisputeActionForm({
  dispute,
  evidenceIds,
  busy,
  onSubmit,
}: {
  dispute: DisputeView;
  evidenceIds: string[];
  busy: boolean;
  onSubmit: (input: DisputeActionInput) => void;
}) {
  const [action, setAction] = useState<DisputeAction>("comment");
  const [comment, setComment] = useState("");
  const [evidenceId, setEvidenceId] = useState("");
  const [resolutionCode, setResolutionCode] = useState("");
  const [reviewCaseId, setReviewCaseId] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  const valid =
    (action === "comment" && comment.trim().length > 0) ||
    (action === "attach_evidence" && evidenceId.length > 0) ||
    (action === "escalate_dispute" && reviewCaseId.trim().length > 0) ||
    (action === "resolve" && resolutionCode.trim().length > 0) ||
    action === "cancel";

  function buildInput(): DisputeActionInput {
    const input: DisputeActionInput = { action };
    if (action === "comment") input.comment = comment.trim();
    if (action === "attach_evidence") input.evidence_id = evidenceId;
    if (action === "escalate_dispute") input.review_case_id = reviewCaseId.trim();
    if (action === "resolve") input.resolution_code = resolutionCode.trim().toUpperCase();
    return input;
  }

  return (
    <div className="grid gap-3 rounded-2xl border border-border bg-surface/40 p-4 sm:grid-cols-2">
      <label className="text-xs text-muted">
        Aksiyon
        <select
          className={`mt-1 ${inputClass}`}
          value={action}
          onChange={(event) => setAction(event.target.value as DisputeAction)}
          disabled={busy || dispute.status === "resolved" || dispute.status === "cancelled"}
        >
          {DISPUTE_ACTIONS.map((value) => (
            <option key={value} value={value}>{value}</option>
          ))}
        </select>
      </label>

      {action === "comment" ? (
        <label className="text-xs text-muted">
          Yorum
          <textarea
            className={`mt-1 ${inputClass}`}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={2000}
          />
        </label>
      ) : null}
      {action === "attach_evidence" ? (
        <label className="text-xs text-muted">
          Kanıt
          <select
            className={`mt-1 ${inputClass}`}
            value={evidenceId}
            onChange={(event) => setEvidenceId(event.target.value)}
          >
            <option value="">Kanıt seçin</option>
            {evidenceIds.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
      ) : null}
      {action === "escalate_dispute" ? (
        <label className="text-xs text-muted">
          Review case ID
          <input
            className={`mt-1 ${inputClass}`}
            value={reviewCaseId}
            onChange={(event) => setReviewCaseId(event.target.value)}
          />
        </label>
      ) : null}
      {action === "resolve" ? (
        <label className="text-xs text-muted">
          Çözüm kodu
          <input
            className={`mt-1 ${inputClass}`}
            value={resolutionCode}
            onChange={(event) => setResolutionCode(event.target.value)}
            maxLength={64}
          />
        </label>
      ) : null}

      <div className="flex items-end">
        <button
          type="button"
          className={action === "resolve" || action === "cancel" ? buttonClass : secondaryButtonClass}
          disabled={!valid || busy || dispute.status === "resolved" || dispute.status === "cancelled"}
          onClick={() => setConfirmOpen(true)}
        >
          Aksiyonu uygula
        </button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="İtiraz aksiyonunu uygula"
        description={`${action} aksiyonu backend yetki ve durum kontrollerinden geçirilecektir.`}
        confirmLabel="Uygula"
        tone={action === "resolve" || action === "cancel" ? "danger" : "default"}
        busy={busy}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          onSubmit(buildInput());
        }}
      />
    </div>
  );
}

export function TransactionDisputesPage() {
  const { detail, refresh: refreshShell } = useTransactionShell();
  const disputes = useAsyncData(() => listDisputes(detail.id), [detail.id]);
  const bundle = useAsyncData(() => getEvidenceBundle(detail.id), [detail.id]);
  const milestones = useAsyncData(() => getMilestones(detail.id), [detail.id]);
  const [reason, setReason] = useState("");
  const [description, setDescription] = useState("");
  const [milestone, setMilestone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openConfirm, setOpenConfirm] = useState(false);

  async function act(operation: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await operation();
      await Promise.all([disputes.refresh(), bundle.refresh(), milestones.refresh(), refreshShell()]);
    } catch (caught) {
      setError(disputeErrorMessage(toApiClientError(caught).code));
    } finally {
      setBusy(false);
    }
  }

  if (disputes.loading && !disputes.data) return <LoadingPanel />;
  if (disputes.error && !disputes.data) {
    return (
      <RetryPanel
        title="İtirazlar yüklenemedi"
        message={disputes.error.userMessage}
        retrying={disputes.loading}
        onRetry={() => void disputes.refresh()}
      />
    );
  }

  const evidenceIds = (bundle.data?.evidence_records ?? []).map((record) => record.id);
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="font-semibold text-heading">İtiraz aç</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            className={inputClass}
            value={reason}
            onChange={(event) => setReason(event.target.value.toUpperCase())}
            placeholder="REASON_CODE"
            maxLength={64}
          />
          <select
            className={inputClass}
            value={milestone}
            onChange={(event) => setMilestone(event.target.value)}
          >
            <option value="">İşlem geneli</option>
            {milestones.data?.milestones.map((item) => (
              <option key={item.id} value={item.id}>{item.title}</option>
            ))}
          </select>
        </div>
        <textarea
          className={inputClass}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Açıklama"
          maxLength={2000}
        />
        <button
          type="button"
          className={buttonClass}
          disabled={busy || !reason.trim() || !description.trim()}
          onClick={() => setOpenConfirm(true)}
        >
          İtiraz aç
        </button>
        {error ? <Notice tone="danger">{error}</Notice> : null}
      </section>

      {disputes.data?.length ? (
        disputes.data.map((dispute) => (
          <article key={dispute.id} className="space-y-4 rounded-2xl border border-border p-4">
            <div>
              <h3 className="font-semibold text-heading">{dispute.reason_code} · {dispute.status}</h3>
              <p className="mt-2 text-sm text-body">{dispute.description}</p>
            </div>
            <DisputeActionForm
              dispute={dispute}
              evidenceIds={evidenceIds}
              busy={busy}
              onSubmit={(input) => void act(() => submitDisputeAction(dispute.id, input))}
            />
          </article>
        ))
      ) : (
        <EmptyState title="İtiraz yok" />
      )}

      <ConfirmDialog
        open={openConfirm}
        title="İtiraz aç"
        description="İtiraz ilgili ödeme serbest bırakmalarını bloklayabilir."
        confirmLabel="Aç"
        tone="danger"
        busy={busy}
        onCancel={() => setOpenConfirm(false)}
        onConfirm={() => {
          setOpenConfirm(false);
          void act(() =>
            openDispute(detail.id, {
              reason_code: reason.trim(),
              description: description.trim(),
              milestone_id: milestone || null,
            }),
          );
        }}
      />
    </div>
  );
}
