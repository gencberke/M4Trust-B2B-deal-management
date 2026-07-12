// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { FundingUnitProjection } from "../../../types/evidence";
import type { PaymentResolution } from "../../../types/payments";
import { OperableUnitsPanel } from "./OperableUnitsPanel";

afterEach(cleanup);

const unit: FundingUnitProjection = {
  id: "unit-1", transaction_id: "tx-1", milestone_id: "m-1", sequence: 1,
  title: "Teslim", amount_minor: 10000, currency: "TRY", eligibility_type: "evidence",
  status: "approved", release_instruction_id: null, release_instruction_status: null,
};

function resolution(operation_type: PaymentResolution["operation_type"]): PaymentResolution {
  return { id: `r-${operation_type}`, transaction_id: "tx-1", funding_unit_id: "unit-1", review_case_id: "case-1", operation_type, status: "authorized", created_at: "2026-07-12T00:00:00Z", updated_at: "2026-07-12T00:00:00Z", approvals: [] };
}

describe("OperableUnitsPanel confirmations", () => {
  it.each([["undo_approval", "GERI-AL"], ["refund", "IADE"]] as const)("%s execution requires exact word", async (operation, word) => {
    const user = userEvent.setup();
    const onExecute = vi.fn();
    render(<OperableUnitsPanel units={[unit]} resolutions={[resolution(operation)]} busy={false} onRequest={vi.fn()} onApprove={vi.fn()} onExecute={onExecute} />);
    await user.click(screen.getByRole("button", { name: "Uygula" }));
    const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "Uygula" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    await user.type(screen.getByLabelText("Onay metni"), word.toLowerCase());
    expect(confirm.disabled).toBe(true);
    expect(onExecute).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("Onay metni"));
    await user.type(screen.getByLabelText("Onay metni"), word);
    expect(confirm.disabled).toBe(false);
    await user.click(confirm);
    expect(onExecute).toHaveBeenCalledOnce();
  });

  it("undo request waits for normal confirmation", async () => {
    const user = userEvent.setup();
    const onRequest = vi.fn();
    render(<OperableUnitsPanel units={[unit]} resolutions={[]} busy={false} onRequest={onRequest} onApprove={vi.fn()} onExecute={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Geri alma talebi" }));
    expect(onRequest).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Talebi oluştur" }));
    expect(onRequest).toHaveBeenCalledWith("unit-1", "undo");
  });
});
