import { Link, useLocation } from "react-router-dom";

import { PageHeading } from "../components/Feedback";
import { buttonClass } from "./shared";

interface ErrorState {
  code?: string;
  requestId?: string | null;
  userMessage?: string;
}

function ErrorPage({ kind }: { kind: "session" | "permission" | "conflict" | "not-found" }) {
  const location = useLocation();
  const state = (location.state as ErrorState | null) ?? {};
  const content = {
    session: {
      title: "Oturum gerekli",
      body: state.userMessage ?? "Bu sayfayı kullanmak için giriş yapmanız gerekiyor.",
      action: <Link className={buttonClass} to="/login">Giriş ekranına git</Link>,
    },
    permission: {
      title: "Bu işlem için yetkiniz yok",
      body: state.userMessage ?? "Doğru entity ile işlem yaptığınızı kontrol edin veya yetkili bir kullanıcıya başvurun.",
      action: <Link className={buttonClass} to="/">Ana sayfaya dön</Link>,
    },
    conflict: {
      title: "Güncel durumla çakışma oluştu",
      body: state.userMessage ?? "Kayıt başka bir işlemle değişmiş olabilir. Sayfayı yenileyin ve backend’in güncel projection’ına göre tekrar deneyin.",
      action: <button className={buttonClass} onClick={() => window.location.reload()}>Sayfayı yenile</button>,
    },
    "not-found": {
      title: "Sayfa bulunamadı",
      body: "Aradığınız frontend route’u bu foundation diliminde tanımlı değil.",
      action: <Link className={buttonClass} to="/">Ana sayfaya dön</Link>,
    },
  }[kind];

  return (
    <div className="mx-auto max-w-2xl rounded-3xl border border-white/10 bg-white/5 p-8 text-center">
      <PageHeading title={content.title} description={content.body} />
      {(state.code || state.requestId) ? (
        <p className="mb-6 text-xs text-slate-500">Kod: {state.code ?? "—"} · İstek: {state.requestId ?? "—"}</p>
      ) : null}
      {content.action}
    </div>
  );
}

export const SessionRequiredPage = () => <ErrorPage kind="session" />;
export const PermissionDeniedPage = () => <ErrorPage kind="permission" />;
export const ConflictPage = () => <ErrorPage kind="conflict" />;
export const NotFoundPage = () => <ErrorPage kind="not-found" />;
