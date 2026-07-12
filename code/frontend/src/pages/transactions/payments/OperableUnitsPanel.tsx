import { useState } from "react";

import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Notice } from "../../../components/Feedback";
import type { FundingUnitProjection } from "../../../types/evidence";
import type { PaymentResolution } from "../../../types/payments";
import { buttonClass, secondaryButtonClass } from "../../shared";
import { executeConfirmWord } from "./paymentsLogic";

type RequestOperation = "undo" | "refund";

export function OperableUnitsPanel({
  units,
  resolutions,
  busy,
  onRequest,
  onApprove,
  onExecute,
}: {
  units: FundingUnitProjection[];
  resolutions: PaymentResolution[];
  busy: boolean;
  onRequest: (id: string, operation: RequestOperation) => void;
  onApprove: (id: string) => void;
  onExecute: (resolution: PaymentResolution) => void;
}) {
  const [request, setRequest] = useState<{ unitId: string; operation: RequestOperation } | null>(null);
  const [execution, setExecution] = useState<PaymentResolution | null>(null);

  return (
    <div className="space-y-4">
      {units.map((unit) => {
        const unitResolutions = resolutions.filter((item) => item.funding_unit_id === unit.id);
        return (
          <article key={unit.id} className="rounded-2xl border border-white/10 p-4">
            <h3 className="text-white">Birim #{unit.sequence} · {unit.status}</h3>
            <div className="mt-3 flex flex-wrap gap-2">
              <button className={secondaryButtonClass} disabled={busy} onClick={() => setRequest({ unitId: unit.id, operation: "undo" })}>
                Geri alma talebi
              </button>
              <button className={secondaryButtonClass} disabled={busy} onClick={() => setRequest({ unitId: unit.id, operation: "refund" })}>
                İade talebi
              </button>
            </div>
            {unitResolutions.map((resolution) => (
              <div key={resolution.id} className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-300">
                <span>{resolution.operation_type} · {resolution.status} · {resolution.approvals.length}/2 onay</span>
                <button className={buttonClass} disabled={busy} onClick={() => onApprove(resolution.id)}>Taraf onayı</button>
                <button className={buttonClass} disabled={busy} onClick={() => setExecution(resolution)}>Uygula</button>
              </div>
            ))}
          </article>
        );
      })}
      {!units.length ? <Notice tone="info">Fonlama birimi yok.</Notice> : null}

      <ConfirmDialog
        open={request !== null}
        title={request?.operation === "refund" ? "İade talebi oluştur" : "Geri alma talebi oluştur"}
        description="Bu talep ödeme çözüm sürecini başlatır ve iki tarafın onayını gerektirebilir."
        confirmLabel="Talebi oluştur"
        busy={busy}
        onCancel={() => setRequest(null)}
        onConfirm={() => {
          if (request) onRequest(request.unitId, request.operation);
          setRequest(null);
        }}
      />
      <ConfirmDialog
        open={execution !== null}
        title="Ödeme çözümünü uygula"
        description="Bu finansal işlem provider çağrısı yapabilir. Sonuç belirsiz kalırsa yeniden uygulamadan önce mutabakat gerekir."
        confirmLabel="Uygula"
        tone="danger"
        requireText={execution ? executeConfirmWord(execution.operation_type) : undefined}
        busy={busy}
        onCancel={() => setExecution(null)}
        onConfirm={() => {
          if (execution) onExecute(execution);
          setExecution(null);
        }}
      />
    </div>
  );
}
