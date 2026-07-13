import { Link, useLocation } from "react-router-dom";

import { PageHeading } from "../components/Feedback";
import {
  conflictReturnPath,
  type ApiErrorNavigationState,
} from "../routes/navigation";
import { buttonClass, secondaryButtonClass } from "./shared";

function ErrorPage({ kind }: { kind: "session" | "permission" | "conflict" | "not-found" }) {
  const location = useLocation();
  const state = (location.state as ApiErrorNavigationState | null) ?? {};
  const returnPath = conflictReturnPath(state);
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
      body: state.userMessage ?? "Kayıt başka bir işlemle değişmiş olabilir. Backend’in güncel projection’ını yeniden yükleyip tekrar deneyin.",
      action: (
        <div className="flex flex-wrap justify-center gap-3">
          {returnPath ? (
            <Link className={buttonClass} replace to={returnPath}>Kaynak sayfaya dön</Link>
          ) : null}
          <Link className={secondaryButtonClass} to="/">Ana sayfaya dön</Link>
        </div>
      ),
    },
    "not-found": {
      title: "Sayfa bulunamadı",
      body: "Aradığınız frontend route’u bu foundation diliminde tanımlı değil.",
      action: <Link className={buttonClass} to="/">Ana sayfaya dön</Link>,
    },
  }[kind];

  return (
    <div className="mx-auto max-w-2xl rounded-3xl border border-border bg-card shadow-card p-8 text-center">
      <PageHeading title={content.title} description={content.body} />
      {(state.code || state.requestId) ? (
        <p className="mb-6 text-xs text-muted">Kod: {state.code ?? "—"} · İstek: {state.requestId ?? "—"}</p>
      ) : null}
      {content.action}
    </div>
  );
}

export const SessionRequiredPage = () => <ErrorPage kind="session" />;
export const PermissionDeniedPage = () => <ErrorPage kind="permission" />;
export const ConflictPage = () => <ErrorPage kind="conflict" />;
export const NotFoundPage = () => <ErrorPage kind="not-found" />;
