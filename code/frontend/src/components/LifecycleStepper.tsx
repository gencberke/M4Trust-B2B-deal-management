import { Link } from "react-router-dom";
import { LIFECYCLE_STEPS, type LifecycleDescriptor, type LifecycleRole } from "../lib/lifecycle";

export function LifecycleStepper({ lifecycle }: { lifecycle: LifecycleDescriptor }) {
  return <section aria-label="İşlem yaşam döngüsü" className="card-surface overflow-x-auto p-5 sm:p-6"><ol className="flex min-w-[44rem] items-start" data-testid="lifecycle-stepper">
    {LIFECYCLE_STEPS.map((label, index) => { const complete = index < lifecycle.stepIndex || Boolean(lifecycle.terminal && lifecycle.tone === "success"); const active = index === lifecycle.stepIndex && !complete; return <li key={label} className="flex min-w-24 flex-1 items-start last:min-w-20"><div className="flex flex-col items-center text-center"><span aria-current={active ? "step" : undefined} className={["grid size-8 place-items-center rounded-full text-xs font-bold", complete ? "bg-positive text-white" : active ? "bg-primary text-white shadow-sm" : "bg-subtle text-muted"].join(" ")}>{complete ? "✓" : index + 1}</span><span className={active ? "mt-2 text-xs font-semibold text-primary" : "mt-2 text-xs font-medium text-muted"}>{label}</span></div>{index < LIFECYCLE_STEPS.length - 1 ? <span className={complete ? "mt-4 h-0.5 min-w-5 flex-1 bg-positive" : "mt-4 h-0.5 min-w-5 flex-1 bg-border"} /> : null}</li>; })}
  </ol></section>;
}

export function MiniLifecycleStepper({ lifecycle }: { lifecycle: LifecycleDescriptor }) {
  return <div aria-label={`${lifecycle.stepLabel}: ${lifecycle.label}`} className="flex items-center gap-1.5">
    {LIFECYCLE_STEPS.map((step, index) => { const complete = index < lifecycle.stepIndex || Boolean(lifecycle.terminal && lifecycle.tone === "success"); const active = index === lifecycle.stepIndex && !complete; return <span key={step} title={step} className={["h-1.5 flex-1 rounded-full", complete ? "bg-positive" : active ? "bg-primary" : "bg-subtle"].join(" ")} />; })}
  </div>;
}

export function NextActionCard({ transactionId, lifecycle, role }: { transactionId: string; lifecycle: LifecycleDescriptor; role: LifecycleRole }) {
  const waiting = lifecycle.nextAction.role === "counterparty"; const noAction = lifecycle.nextAction.role === "none" || lifecycle.nextAction.role === "system"; const prefix = waiting ? "Karşı taraf bekleniyor" : noAction ? "Durum" : "Senin aksiyonun";
  return <aside className="card-surface flex flex-col gap-4 border-l-4 border-l-primary p-5 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-primary">Sıradaki adım</p><h2 className="mt-2 text-lg font-semibold text-heading">{prefix}: {lifecycle.nextAction.label}</h2><p className="mt-1 text-sm leading-6 text-muted">{lifecycle.nextAction.blockedReason ?? lifecycle.description}</p></div>{!waiting && !noAction ? <Link className="button-primary shrink-0" to={`/transactions/${transactionId}/${lifecycle.nextAction.targetSection}`}>{lifecycle.nextAction.label}</Link> : null}<span className="sr-only">Aktör rolü: {role}</span></aside>;
}
