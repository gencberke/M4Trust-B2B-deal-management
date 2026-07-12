import { Link } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { Notice, PageHeading, RetryPanel } from "../components/Feedback";
import { useEntities } from "../entities/EntityContext";
import { buttonClass, secondaryButtonClass } from "./shared";

export function HomePage() {
  const { user, loading, bootstrapError, refresh } = useAuth();
  const { selectedEntity, entities } = useEntities();

  return (
    <>
      <PageHeading
        eyebrow="Faz 8A · Frontend Foundation"
        title="Güvenli B2B akışları için hesap temeli"
        description="Bu sürüm oturum, CSRF ve legal entity kontratlarını görünür kılar. İşlem, davet ve ödeme ekranları sonraki dikey dilimlere aittir."
      />
      {bootstrapError ? (
        <RetryPanel
          title="Oturum durumu yüklenemedi"
          message={bootstrapError.userMessage}
          retrying={loading}
          onRetry={() => void refresh()}
        />
      ) : (
        <div className="grid gap-5 md:grid-cols-3">
          <section className="rounded-3xl border border-white/10 bg-white/5 p-6 md:col-span-2">
            <p className="text-sm font-medium text-cyan-200">Backend kaynaklı durum</p>
            {loading ? (
              <p className="mt-4 text-sm text-slate-400">Oturum kontrol ediliyor…</p>
            ) : user ? (
              <div className="mt-4 space-y-4">
                <div>
                  <p className="text-2xl font-semibold text-white">Hoş geldin, {user.first_name}.</p>
                  <p className="mt-1 text-sm text-slate-400">Aktif oturum cookie tabanlıdır; auth token tarayıcı depolamasına yazılmaz.</p>
                </div>
                {selectedEntity ? (
                  <Notice tone="success">İşlem yapılan entity: <strong>{selectedEntity.legal_name}</strong></Notice>
                ) : (
                  <Notice tone="warning">İşlem yapabilmek için legal entity profili oluşturun.</Notice>
                )}
                <div>
                  <Link className={buttonClass} to="/transactions">İşlemlere git</Link>
                </div>
              </div>
            ) : (
              <div className="mt-4">
                <p className="text-2xl font-semibold text-white">Oturum bulunamadı.</p>
                <p className="mt-2 text-sm text-slate-400">Hesabınızla giriş yapın veya yeni hesap oluşturun.</p>
                <div className="mt-5 flex gap-3">
                  <Link className={buttonClass} to="/login">Giriş yap</Link>
                  <Link className={secondaryButtonClass} to="/register">Kayıt ol</Link>
                </div>
              </div>
            )}
          </section>
          <aside className="rounded-3xl border border-white/10 bg-gradient-to-b from-indigo-400/10 to-cyan-400/5 p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-200">Hazır seam’ler</p>
            <ul className="mt-4 space-y-3 text-sm leading-6 text-slate-300">
              <li>Merkezi `/api` client</li>
              <li>Session + CSRF koruması</li>
              <li>Acting-entity header’ı</li>
              <li>401 / 403 / 409 akışları</li>
              <li>Backend projection odaklı tipler</li>
            </ul>
            {user ? <p className="mt-6 text-xs text-slate-500">Backend’in döndürdüğü entity sayısı: {entities.length}</p> : null}
          </aside>
        </div>
      )}
    </>
  );
}
