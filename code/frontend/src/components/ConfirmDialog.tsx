import { useEffect, useId, useRef, useState } from "react";

import { buttonClass, inputClass, secondaryButtonClass } from "../pages/shared";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  tone?: "default" | "danger";
  requireText?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Erişilebilir onay modalı: focus trap, `Esc` iptal, `aria-modal`, başlangıç
 * odağı iptal düğmesinde (master §10). `requireText` verilirse (finansal
 * aksiyonlar), kullanıcı metni birebir yazana kadar onay düğmesi kilitli.
 * Kapanışta odak tetikleyiciye döner.
 *
 * Gövde yalnız `open` iken mount edilir; böylece yazılan onay metni her
 * açılışta doğal olarak sıfırlanır (efekt/render içinde setState gerekmez).
 */
export function ConfirmDialog(props: ConfirmDialogProps) {
  if (!props.open) return null;
  return <ConfirmDialogBody {...props} />;
}

function ConfirmDialogBody({
  title,
  description,
  confirmLabel,
  tone = "default",
  requireText,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const triggerRef = useRef<Element | null>(null);
  const [typed, setTyped] = useState("");
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    triggerRef.current = document.activeElement;
    // Yıkıcı diyalogda Enter yanlışlıkla onaylamasın diye odak iptal düğmesinde.
    cancelRef.current?.focus();
    return () => {
      if (triggerRef.current instanceof HTMLElement) triggerRef.current.focus();
    };
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), [href], input:not([disabled]), textarea",
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  const confirmDisabled = busy || (requireText != null && typed !== requireText);
  const confirmClass =
    tone === "danger"
      ? "inline-flex items-center justify-center rounded-2xl bg-rose-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
      : buttonClass;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-heading/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        className="w-full max-w-md rounded-3xl border border-border bg-card p-6 shadow-xl"
      >
        <h2 id={titleId} className="text-lg font-semibold text-heading">
          {title}
        </h2>
        <p id={descId} className="mt-2 text-sm text-body">
          {description}
        </p>
        {requireText != null ? (
          <label className="mt-4 block text-xs text-muted">
            Onaylamak için <strong className="text-heading">{requireText}</strong> yazın
            <input
              className={`mt-2 ${inputClass}`}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              aria-label="Onay metni"
            />
          </label>
        ) : null}
        <div className="mt-6 flex justify-end gap-3">
          <button ref={cancelRef} className={secondaryButtonClass} onClick={onCancel} disabled={busy}>
            Vazgeç
          </button>
          <button className={confirmClass} onClick={onConfirm} disabled={confirmDisabled}>
            {busy ? "İşleniyor…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
