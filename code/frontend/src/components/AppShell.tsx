import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { useEntities } from "../entities/EntityContext";

function navClass({ isActive }: { isActive: boolean }): string {
  return [
    "rounded-full px-3 py-2 text-sm transition",
    isActive ? "bg-primary text-white shadow-sm" : "text-muted hover:bg-primary-soft hover:text-primary",
  ].join(" ");
}

export function AppShell() {
  const { user } = useAuth();
  const {
    entities,
    selectedEntityId,
    selectEntity,
    loading,
    error,
    refreshEntities,
  } = useEntities();

  return (
    <div className="min-h-screen bg-surface text-body">
      <header className="relative z-10 border-b border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-5 py-4">
          <NavLink to="/" className="mr-auto flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-2xl bg-primary font-black text-white">M4</span>
            <span>
              <strong className="block text-sm tracking-wide text-heading">M4Trust</strong>
              <span className="block text-xs text-muted">B2B güven katmanı</span>
            </span>
          </NavLink>

          <nav className="flex w-full flex-wrap items-center justify-between gap-1 sm:w-auto sm:justify-start">
            <NavLink to="/" className={navClass}>Ana sayfa</NavLink>
            {user ? <NavLink to="/transactions" className={navClass}>İşlemler</NavLink> : null}
            {user ? <NavLink to="/me" className={navClass}>Hesabım</NavLink> : null}
            {user ? <NavLink to="/entities/new" className={navClass}>Şirket ekle</NavLink> : null}
            {user ? <NavLink to="/logout" className={navClass}>Çıkış</NavLink> : <NavLink to="/login" className={navClass}>Giriş</NavLink>}
          </nav>
        </div>

        {user ? (
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 pb-4">
            <p className="text-xs text-muted">
              {user.first_name} {user.last_name} · {user.email}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {error ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-rose-700">Entity listesi yüklenemedi.</span>
                  <button
                    className="text-xs font-semibold text-primary hover:text-primary"
                    onClick={() => void refreshEntities()}
                  >
                    Tekrar dene
                  </button>
                </div>
              ) : (
                <label className="flex items-center gap-2 text-xs text-muted">
                  İşlem yapılan tüzel/gerçek kişi
                  <select
                    className="min-w-56 rounded-xl border border-border bg-card px-3 py-2 text-sm text-heading outline-none focus:border-primary"
                    value={selectedEntityId ?? ""}
                    onChange={(event) => selectEntity(event.target.value || null)}
                    disabled={loading || entities.length === 0}
                    aria-label="İşlem yapılan entity"
                  >
                    {entities.length === 0 ? (
                      <option value="">
                        {loading ? "Entity listesi yükleniyor" : "Kayıtlı entity yok"}
                      </option>
                    ) : null}
                    {entities.map((entity) => (
                      <option key={entity.id} value={entity.id}>{entity.legal_name}</option>
                    ))}
                  </select>
                </label>
              )}
              {selectedEntityId ? (
                <NavLink className="text-xs font-medium text-primary hover:text-primary" to={`/entities/${selectedEntityId}`}>
                  Profili aç
                </NavLink>
              ) : null}
            </div>
          </div>
        ) : null}
      </header>

      <main className="relative z-0 mx-auto max-w-6xl px-4 py-8 sm:px-5 sm:py-10">
        <Outlet />
      </main>
    </div>
  );
}
