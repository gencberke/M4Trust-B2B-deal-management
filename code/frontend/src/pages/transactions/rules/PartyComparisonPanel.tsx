import { StatusBadge } from "../../../components/StatusBadge";
import { participantStatusMap, reviewSeverityMap } from "../../../lib/statusMaps";
import type { ParticipantPublicView, ParticipantRole } from "../../../types/participants";
import type { RedactedExtraction } from "../../../types/transactions";
import type { ReviewCase } from "../../../types/reviews";

const ROLE_LABEL: Record<ParticipantRole, string> = { buyer: "Alıcı", seller: "Satıcı" };

/**
 * Extracted (sözleşmeden) vs declared (taraf profili) ad karşılaştırması.
 * Uyuşmazlık gerçeği backend review case'lerinden gelir — frontend istemci
 * tarafı diff yapmaz, yalnız string gösterir (master §H / plan §H).
 */
export function PartyComparisonPanel({
  extraction,
  participants,
  mismatchCases,
}: {
  extraction: RedactedExtraction | null;
  participants: ParticipantPublicView[];
  mismatchCases: ReviewCase[];
}) {
  if (!extraction) {
    return <p className="text-sm text-muted">Karşılaştırma için extraction bekleniyor.</p>;
  }

  const roles: ParticipantRole[] = ["buyer", "seller"];

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {roles.map((role) => {
          const extractedName = extraction.parties[role]?.name ?? "—";
          const participant = participants.find((p) => p.role === role) ?? null;
          return (
            <div key={role} className="rounded-2xl border border-border bg-subtle/60 p-4">
              <p className="text-xs uppercase tracking-wide text-muted">{ROLE_LABEL[role]}</p>
              <dl className="mt-2 space-y-2 text-sm">
                <div>
                  <dt className="text-xs text-muted">Sözleşmeden</dt>
                  <dd className="text-heading">{extractedName}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Beyan edilen</dt>
                  <dd className="text-heading">{participant?.display_name ?? "—"}</dd>
                </div>
                <div className="flex items-center gap-2">
                  <dt className="text-xs text-muted">Durum</dt>
                  <dd>
                    {participant ? (
                      <StatusBadge value={participant.status} map={participantStatusMap} />
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
              </dl>
            </div>
          );
        })}
      </div>

      {mismatchCases.length > 0 ? (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-amber-800">Taraf uyuşmazlığı incelemeleri</h3>
          {mismatchCases.map((c) => (
            <div key={c.id} className="rounded-2xl border border-amber-300 bg-amber-400/5 p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-muted">{c.reason_code}</span>
                <StatusBadge value={c.severity} map={reviewSeverityMap} />
              </div>
              <p className="mt-1 text-body">{c.description}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
