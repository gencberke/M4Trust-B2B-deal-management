import { useState } from "react";

import { listParticipants } from "../../api/participants";
import { listReviews, submitReviewAction } from "../../api/reviews";
import { toApiClientError } from "../../api/client";
import { LoadingPanel, RetryPanel } from "../../components/Feedback";
import { useTransactionShell } from "../../components/TransactionShell";
import { useAsyncData } from "../../lib/useAsyncData";
import type { ReviewActionRequest } from "../../types/reviews";
import { PartyComparisonPanel } from "./rules/PartyComparisonPanel";
import { ReviewCasesPanel } from "./rules/ReviewCasesPanel";
import { ValidatorFindingsPanel } from "./rules/ValidatorFindingsPanel";
import { reviewActionErrorMessage, splitCasesBySource } from "./rules/rulesLogic";

export function TransactionRulesPage() {
  const { detail, refresh: refreshShell } = useTransactionShell();

  const participants = useAsyncData(() => listParticipants(detail.id), [detail.id]);
  const reviews = useAsyncData(() => listReviews(detail.id), [detail.id]);

  const [busyCaseId, setBusyCaseId] = useState<string | null>(null);
  const [errorByCase, setErrorByCase] = useState<Record<string, string | undefined>>({});

  async function onAction(caseId: string, body: ReviewActionRequest) {
    setBusyCaseId(caseId);
    setErrorByCase((prev) => ({ ...prev, [caseId]: undefined }));
    try {
      await submitReviewAction(caseId, body);
      await reviews.refresh();
      await refreshShell();
    } catch (caught) {
      const err = toApiClientError(caught);
      setErrorByCase((prev) => ({ ...prev, [caseId]: reviewActionErrorMessage(err.code) }));
    } finally {
      setBusyCaseId(null);
    }
  }

  const split = reviews.data ? splitCasesBySource(reviews.data) : null;

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-white">Taraf karşılaştırması</h2>
        {participants.loading && !participants.data ? (
          <LoadingPanel label="Taraflar yükleniyor…" />
        ) : participants.error && !participants.data ? (
          <RetryPanel
            title="Taraflar yüklenemedi"
            message={participants.error.userMessage}
            retrying={participants.loading}
            onRetry={() => void participants.refresh()}
          />
        ) : (
          <PartyComparisonPanel
            extraction={detail.extraction}
            participants={participants.data ?? []}
            mismatchCases={split?.partyMismatch ?? []}
          />
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-base font-semibold text-white">Doğrulama bulguları</h2>
        <ValidatorFindingsPanel validator={detail.validator} />
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-white">İnceleme kayıtları</h2>
          <button
            type="button"
            className="text-sm font-medium text-cyan-300 hover:text-cyan-200 disabled:opacity-50"
            onClick={() => void reviews.refresh()}
            disabled={reviews.loading}
          >
            Yenile
          </button>
        </div>
        {reviews.loading && !reviews.data ? (
          <LoadingPanel label="İncelemeler yükleniyor…" />
        ) : reviews.error && !reviews.data ? (
          <RetryPanel
            title="İncelemeler yüklenemedi"
            message={reviews.error.userMessage}
            retrying={reviews.loading}
            onRetry={() => void reviews.refresh()}
          />
        ) : (
          <ReviewCasesPanel
            cases={split?.others ?? []}
            onAction={onAction}
            busyCaseId={busyCaseId}
            errorByCase={errorByCase}
          />
        )}
      </section>
    </div>
  );
}
