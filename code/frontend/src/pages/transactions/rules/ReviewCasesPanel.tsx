import { useState } from "react";

import { EmptyState, Notice } from "../../../components/Feedback";
import { StatusBadge } from "../../../components/StatusBadge";
import { Timeline } from "../../../components/Timeline";
import { shortId } from "../../../lib/format";
import {
  reviewPhaseMap,
  reviewSeverityMap,
  reviewSourceMap,
  reviewStatusMap,
} from "../../../lib/statusMaps";
import type { ReviewActionRequest, ReviewActionType, ReviewCaseWithActions } from "../../../types/reviews";
import { buttonClass, inputClass } from "../../shared";
import {
  isResolveAction,
  REVIEW_ACTION_LABELS,
  safeActionPayloadEntries,
} from "./rulesLogic";

const RESOLUTION_QUICK_PICKS = ["VIDEO_FALSE_POSITIVE", "SUPERSEDED_BY_CLEAN_EVIDENCE"];
const ACTION_ORDER: ReviewActionType[] = [
  "comment",
  "request_evidence",
  "resolve_continue",
  "resolve_reject",
  "escalate",
  "escalate_dispute",
  "cancel",
];

export function ReviewCasesPanel({
  cases,
  onAction,
  busyCaseId,
  errorByCase,
}: {
  cases: ReviewCaseWithActions[];
  onAction: (caseId: string, body: ReviewActionRequest) => void;
  busyCaseId: string | null;
  errorByCase: Record<string, string | undefined>;
}) {
  if (cases.length === 0) {
    return <EmptyState title="Açık inceleme yok" description="Bu işlem için inceleme kaydı bulunmuyor." />;
  }
  return (
    <div className="space-y-4">
      {cases.map((item) => (
        <ReviewCaseCard
          key={item.case.id}
          item={item}
          busy={busyCaseId === item.case.id}
          error={errorByCase[item.case.id]}
          onAction={(body) => onAction(item.case.id, body)}
        />
      ))}
    </div>
  );
}

function ReviewCaseCard({
  item,
  busy,
  error,
  onAction,
}: {
  item: ReviewCaseWithActions;
  busy: boolean;
  error: string | undefined;
  onAction: (body: ReviewActionRequest) => void;
}) {
  const { case: c, actions } = item;
  const [action, setAction] = useState<ReviewActionType>("comment");
  const [comment, setComment] = useState("");
  const [resolutionCode, setResolutionCode] = useState("");
  const terminal = c.status === "resolved" || c.status === "cancelled";

  function submit() {
    const body: ReviewActionRequest = { action };
    if (comment.trim()) body.comment = comment.trim();
    if (isResolveAction(action) && resolutionCode.trim()) body.resolution_code = resolutionCode.trim();
    onAction(body);
  }

  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-white">{c.title}</h3>
        <StatusBadge value={c.severity} map={reviewSeverityMap} />
        <StatusBadge value={c.status} map={reviewStatusMap} />
        <StatusBadge value={c.phase} map={reviewPhaseMap} />
        <StatusBadge value={c.source_type} map={reviewSourceMap} />
      </div>
      <p className="mt-1 font-mono text-xs text-slate-500">{c.reason_code}</p>
      <p className="mt-2 text-sm text-slate-300">{c.description}</p>

      {actions.length > 0 ? (
        <div className="mt-4">
          <h4 className="mb-2 text-xs uppercase tracking-wide text-slate-500">Aksiyon geçmişi</h4>
          <Timeline
            emptyLabel="Aksiyon yok."
            items={actions.map((a) => ({
              id: a.id,
              title: REVIEW_ACTION_LABELS[a.action] ?? a.action,
              timestamp: a.created_at,
              children: (
                <div className="space-y-0.5">
                  <p className="text-slate-500">Aktör: {shortId(a.actor_user_id)}</p>
                  {safeActionPayloadEntries(a.payload).map((e) => (
                    <p key={e.label}>
                      <span className="text-slate-500">{e.label}:</span> {e.value}
                    </p>
                  ))}
                </div>
              ),
            }))}
          />
        </div>
      ) : null}

      {terminal ? (
        <Notice tone="info">Bu inceleme kapandı; yeni aksiyon eklenemez.</Notice>
      ) : (
        <div className="mt-4 space-y-3 border-t border-white/10 pt-4">
          <p className="text-xs text-slate-500">
            Aksiyon yetkisi backend tarafından belirlenir (yorum: yönetici/onaylayan/platform;
            uyuşmazlığa taşıma: yalnız taraf onaylayanı; diğerleri: yalnız platform). Yetkiniz yoksa
            gönderim 403 döner.
          </p>
          <label className="block text-sm text-slate-300">
            Aksiyon
            <select
              className={`mt-1 block ${inputClass}`}
              value={action}
              onChange={(e) => setAction(e.target.value as ReviewActionType)}
            >
              {ACTION_ORDER.map((a) => (
                <option key={a} value={a}>
                  {REVIEW_ACTION_LABELS[a]}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm text-slate-300">
            Yorum (isteğe bağlı)
            <textarea
              className={`mt-1 block h-20 ${inputClass}`}
              value={comment}
              maxLength={2000}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Hassas/token benzeri içerik reddedilir."
            />
          </label>
          {isResolveAction(action) ? (
            <div className="space-y-2">
              <label className="block text-sm text-slate-300">
                Çözüm kodu
                <input
                  className={`mt-1 block ${inputClass}`}
                  value={resolutionCode}
                  onChange={(e) => setResolutionCode(e.target.value)}
                  placeholder="A-Z0-9_"
                />
              </label>
              <div className="flex flex-wrap gap-2">
                {RESOLUTION_QUICK_PICKS.map((code) => (
                  <button
                    key={code}
                    type="button"
                    className="rounded-full border border-white/15 px-3 py-1 text-xs text-slate-200 hover:bg-white/10"
                    onClick={() => setResolutionCode(code)}
                  >
                    {code}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {error ? <Notice tone="danger">{error}</Notice> : null}

          <button type="button" className={buttonClass} disabled={busy} onClick={submit}>
            {busy ? "Gönderiliyor…" : "Aksiyonu gönder"}
          </button>
        </div>
      )}
    </div>
  );
}
