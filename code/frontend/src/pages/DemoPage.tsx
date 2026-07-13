import { useState } from "react";
import { Link } from "react-router-dom";

import { createDemoScenario, type DemoTargetState } from "../api/demo";
import { toApiClientError } from "../api/client";
import { EmptyState, Notice, PageHeading } from "../components/Feedback";
import { useDemo } from "../demo/DemoContext";
import { buttonClass, secondaryButtonClass } from "./shared";

const DEMO_FLOW = [
  {
    number: "01",
    title: "Sözleşme ve AI çıkarımı",
    description: "Çıkarılan tarafları, kuralları ve validator sonucunu gösterin.",
    detail: "Kurallar sekmesi · manuel inceleme gerekçeleri",
    to: "/transactions/demo01-awaiting-review/rules",
  },
  {
    number: "02",
    title: "Taraflar ve davet",
    description: "Alıcı/satıcı profillerini, davet durumunu ve yeniden link üretimini gösterin.",
    detail: "Taraflar sekmesi · davet listesi",
    to: "/transactions/demo02-awaiting-ratification/parties",
  },
  {
    number: "03",
    title: "Politika ve çift onay",
    description: "Kilitli takip politikasını, package readiness'i ve iki taraf onayını anlatın.",
    detail: "Onay sekmesi · policy → package → ratification",
    to: "/transactions/demo02-awaiting-ratification/ratification",
  },
  {
    number: "04",
    title: "Fonlama",
    description: "Milestone'lardan türeyen funding unit ve pool ödeme kayıtlarını gösterin.",
    detail: "Ödemeler sekmesi · fonlanmış aktif işlem",
    to: "/transactions/demo03-active/payments",
  },
  {
    number: "05",
    title: "Kısmi teslimat",
    description: "İlk e-irsaliye sonrası tamamlanan dilimi ve bekleyen ikinci dilimi gösterin.",
    detail: "Teslimat sekmesi · milestone ve kanıt zinciri",
    to: "/transactions/demo04-active-partial/fulfillment",
  },
  {
    number: "06A",
    title: "İtiraz dalı",
    description: "Yetkili insan aksiyonuyla açılan dispute'u ve release blokajını gösterin.",
    detail: "İtirazlar sekmesi · alternatif risk dalı",
    to: "/transactions/demo06-disputed/disputes",
    branch: true,
  },
  {
    number: "06B",
    title: "Settlement ve kapanış",
    description: "Kanıt → release instruction → approved funding unit → settled zincirini kapatın.",
    detail: "Ödemeler sekmesi · başarılı ana yol",
    to: "/transactions/demo05-settled/payments",
  },
] as const;

const SCENARIOS: { state: DemoTargetState; title: string; description: string }[] = [
  { state: "awaiting_review", title: "İnceleme bekliyor", description: "Manuel inceleme kapısındaki işlem." },
  { state: "awaiting_ratification", title: "Onay bekliyor", description: "İki taraf onayını bekleyen işlem." },
  { state: "active", title: "Aktif", description: "Fonlanmış ve teslimata hazır işlem." },
  { state: "active_partial", title: "Kısmi teslimat", description: "İlk teslimat dilimi tamamlanmış işlem." },
  { state: "disputed", title: "İtirazlı", description: "Açık dispute içeren işlem." },
  { state: "settled", title: "Kapandı", description: "Ödeme yaşam döngüsü tamamlanmış işlem." },
];

export function DemoPage() {
  const { enabled, loading } = useDemo();
  const [busy, setBusy] = useState<DemoTargetState | null>(null);
  const [created, setCreated] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  if (loading) return null;
  if (!enabled) return <EmptyState title="Sayfa bulunamadı" description="Demo araçları bu ortamda açık değil." />;

  async function create(state: DemoTargetState) {
    setBusy(state);
    setError(null);
    try {
      const result = await createDemoScenario({ scenario: state });
      setCreated((current) => ({ ...current, [state]: result.transaction_id }));
    } catch (caught) {
      setError(toApiClientError(caught).userMessage);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeading
        eyebrow="Gösterim modu"
        title="M4Trust baştan sona demo akışı"
        description="Kartları sırayla açın. Ana yol settlement ile kapanır; itiraz kartı aynı yaşam döngüsünün kontrollü risk dalını gösterir."
      />

      <Notice tone="info">
        <strong>Sunum önerisi:</strong> Önce 01–05 arasını izleyin; ardından 06A ile risk dalını,
        06B ile başarılı kapanışı karşılaştırın. Her kart doğrudan gösterilecek sekmeyi açar.
      </Notice>

      <ol className="mt-6 grid gap-4 lg:grid-cols-2">
        {DEMO_FLOW.map((step) => (
          <li key={step.number} className={`card-surface relative overflow-hidden p-6 ${step.branch ? "border-amber-300" : ""}`}>
            <div className="flex items-start gap-4">
              <span className={`grid size-12 shrink-0 place-items-center rounded-2xl text-sm font-extrabold ${step.branch ? "bg-warning-soft text-amber-800" : "bg-primary text-white"}`}>
                {step.number}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-bold text-heading">{step.title}</h2>
                  {step.branch ? <span className="rounded-full bg-warning-soft px-2.5 py-1 text-xs font-bold text-amber-800">Risk dalı</span> : null}
                </div>
                <p className="mt-2 text-sm leading-6 text-body">{step.description}</p>
                <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted">{step.detail}</p>
                <Link className={`mt-5 ${buttonClass}`} to={step.to}>Bu adımı göster</Link>
              </div>
            </div>
          </li>
        ))}
      </ol>

      <section className="mt-12 border-t border-border pt-8">
        <div className="mb-5">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-primary">Yardımcı araç</p>
          <h2 className="mt-2 text-2xl font-bold text-heading">Tekil senaryo üret</h2>
          <p className="mt-2 text-sm text-muted">Ana sunum rotasından bağımsız yeni bir işlem gerektiğinde kullanın.</p>
        </div>
        {error ? <div className="mb-5"><Notice tone="danger">{error}</Notice></div> : null}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {SCENARIOS.map((scenario) => (
            <article key={scenario.state} className="card-surface p-5">
              <h3 className="font-semibold text-heading">{scenario.title}</h3>
              <p className="mt-2 min-h-10 text-sm text-muted">{scenario.description}</p>
              {created[scenario.state] ? (
                <Link className={`mt-4 ${secondaryButtonClass}`} to={`/transactions/${created[scenario.state]}/overview`}>İşleme git</Link>
              ) : (
                <button className={`mt-4 ${secondaryButtonClass}`} disabled={busy !== null} onClick={() => void create(scenario.state)}>
                  {busy === scenario.state ? "Oluşturuluyor…" : "Yeni senaryo oluştur"}
                </button>
              )}
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
