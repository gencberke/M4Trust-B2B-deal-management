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
        eyebrow="Güvenli işlem orkestrasyonu"
        title="B2B anlaşmalarını kanıta dayalı yönetin"
        description="Sözleşme yüklemeden taraf onayına, teslimat kanıtından kontrollü ödemeye kadar işlem yaşam döngüsünü tek yerde izleyin."
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
          <section className="rounded-3xl border border-border bg-card shadow-card p-6 md:col-span-2">
            <p className="text-sm font-medium text-primary">Hesap ve yetki durumu</p>
            {loading ? (
              <p className="mt-4 text-sm text-muted">Oturum kontrol ediliyor…</p>
            ) : user ? (
              <div className="mt-4 space-y-4">
                <div>
                  <p className="text-2xl font-semibold text-heading">Hoş geldin, {user.first_name}.</p>
                  <p className="mt-1 text-sm text-muted">Aktif oturum cookie tabanlıdır; auth token tarayıcı depolamasına yazılmaz.</p>
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
                <p className="text-2xl font-semibold text-heading">Oturum bulunamadı.</p>
                <p className="mt-2 text-sm text-muted">Hesabınızla giriş yapın veya yeni hesap oluşturun.</p>
                <div className="mt-5 flex gap-3">
                  <Link className={buttonClass} to="/login">Giriş yap</Link>
                  <Link className={secondaryButtonClass} to="/register">Kayıt ol</Link>
                </div>
              </div>
            )}
          </section>
          <aside className="rounded-3xl border border-border bg-gradient-to-b from-primary-soft to-card p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-200">Güvenlik temeli</p>
            <ul className="mt-4 space-y-3 text-sm leading-6 text-body">
              <li>HttpOnly oturum ve CSRF koruması</li>
              <li>Entity kapsamlı erişim denetimi</li>
              <li>Değiştirilemez onay paketi geçmişi</li>
              <li>Şifreli sözleşme ve kanıt saklama</li>
              <li>Tekrara dayanıklı ödeme işlemleri</li>
            </ul>
            {user ? <p className="mt-6 text-xs text-muted">Hesabınıza bağlı entity sayısı: {entities.length}</p> : null}
          </aside>
        </div>
      )}
    </>
  );
}
