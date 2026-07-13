import { useState } from "react";
import { Link } from "react-router-dom";
import { createDemoScenario, type DemoTargetState } from "../api/demo";
import { toApiClientError } from "../api/client";
import { EmptyState, Notice, PageHeading } from "../components/Feedback";
import { useDemo } from "../demo/DemoContext";
import { buttonClass } from "./shared";

const SCENARIOS: { state: DemoTargetState; title: string; description: string }[] = [
  { state: "awaiting_ratification", title: "Onay bekliyor", description: "Politikası kilitli, iki taraf onayını bekleyen işlem." }, { state: "active", title: "Aktif", description: "Fonlanmış ve teslimat kanıtına hazır işlem." },
  { state: "active_partial", title: "Kısmi teslimat", description: "İlk teslimat dilimi tamamlanmış aktif işlem." }, { state: "settled", title: "Kapandı", description: "Teslimat ve ödeme yaşam döngüsü tamamlanmış işlem." },
  { state: "disputed", title: "İtirazlı", description: "Gerçek itiraz servisi üzerinden açılmış işlem." }, { state: "awaiting_review", title: "İnceleme bekliyor", description: "Manuel inceleme kapısında bekleyen işlem." },
];
export function DemoPage() {
  const { enabled, loading } = useDemo(); const [busy, setBusy] = useState<DemoTargetState | null>(null); const [created, setCreated] = useState<Record<string, string>>({}); const [error, setError] = useState<string | null>(null);
  if (loading) return null;
  if (!enabled) return <EmptyState title="Sayfa bulunamadı" description="Demo araçları bu ortamda açık değil." />;
  async function create(state: DemoTargetState) { setBusy(state); setError(null); try { const result = await createDemoScenario({ scenario: state }); setCreated((current) => ({ ...current, [state]: result.transaction_id })); } catch (caught) { setError(toApiClientError(caught).userMessage); } finally { setBusy(null); } }
  return <><PageHeading eyebrow="Demo araçları" title="Senaryo matrisi" description="Adlandırılmış bir işlemi tek tıkla oluşturun; ardından işlem sayfasındaki demo paneliyle ilerletin." />{error ? <div className="mb-5"><Notice tone="danger">{error}</Notice></div> : null}<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">{SCENARIOS.map((s) => <article key={s.state} className="card-surface p-6"><h2 className="text-lg font-semibold text-heading">{s.title}</h2><p className="mt-2 min-h-12 text-sm text-muted">{s.description}</p>{created[s.state] ? <Link className={`mt-5 ${buttonClass}`} to={`/transactions/${created[s.state]}/overview`}>İşleme git</Link> : <button className={`mt-5 ${buttonClass}`} disabled={busy !== null} onClick={() => void create(s.state)}>{busy === s.state ? "Oluşturuluyor…" : "Senaryo oluştur"}</button>}</article>)}</div></>;
}
