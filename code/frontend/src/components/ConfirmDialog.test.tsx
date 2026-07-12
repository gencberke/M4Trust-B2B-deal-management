// @vitest-environment jsdom
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConfirmDialog } from "./ConfirmDialog";

afterEach(cleanup);

function Harness({
  requireText,
  onConfirm,
}: {
  requireText?: string;
  onConfirm?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Aç</button>
      <ConfirmDialog
        open={open}
        title="Onay"
        description="Emin misiniz?"
        confirmLabel="Onayla"
        requireText={requireText}
        onConfirm={() => {
          onConfirm?.();
          setOpen(false);
        }}
        onCancel={() => setOpen(false)}
      />
    </>
  );
}

describe("ConfirmDialog", () => {
  it("açılışta odak iptal düğmesinde ve kapanışta tetikleyiciye döner", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Aç" });
    await user.click(trigger);

    const cancel = screen.getByRole("button", { name: "Vazgeç" });
    expect(document.activeElement).toBe(cancel);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("requireText doğru yazılana kadar onay düğmesi kilitli", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<Harness requireText="ONAYLA" onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "Aç" }));

    const confirm = screen.getByRole("button", { name: "Onayla" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    await user.click(screen.getByLabelText("Onay metni"));
    await user.keyboard("ONAYLA");
    expect(confirm.disabled).toBe(false);
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("Tab odağı diyalog içinde döngüler (focus trap)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Aç" }));

    const cancel = screen.getByRole("button", { name: "Vazgeç" });
    const confirm = screen.getByRole("button", { name: "Onayla" });
    expect(document.activeElement).toBe(cancel);
    // Son elemandan sonra Tab başa sarar.
    (confirm as HTMLButtonElement).focus();
    await user.tab();
    expect(document.activeElement).toBe(cancel);
  });
});
