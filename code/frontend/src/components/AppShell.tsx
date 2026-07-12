import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { useEntities } from "../entities/EntityContext";

function navClass({ isActive }: { isActive: boolean }): string {
  return [
    "rounded-full px-3 py-2 text-sm transition",
    isActive ? "bg-white text-slate-950" : "text-slate-300 hover:bg-white/10 hover:text-white",
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
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="pointer-events-none fixed inset-x-0 top-0 h-96 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.15),transparent_45%),radial-gradient(circle_at_top_right,rgba(129,140,248,0.12),transparent_40%)]" />
      <header className="relative z-10 border-b border-white/10 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-5 py-4">
          <NavLink to="/" className="mr-auto flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-2xl bg-cyan-300 font-black text-slate-950">M4</span>
            <span>
              <strong className="block text-sm tracking-wide text-white">M4Trust</strong>
              <span className="block text-xs text-slate-400">B2B güven katmanı</span>
            </span>
          </NavLink>

          <nav className="flex items-center gap-1">
            <NavLink to="/" className={navClass}>Ana sayfa</NavLink>
            {user ? <NavLink to="/transactions" className={navClass}>İşlemler</NavLink> : null}
            {user ? <NavLink to="/me" className={navClass}>Hesabım</NavLink> : null}
            {user ? <NavLink to="/entities/new" className={navClass}>Şirket ekle</NavLink> : null}
            {user ? <NavLink to="/logout" className={navClass}>Çıkış</NavLink> : <NavLink to="/login" className={navClass}>Giriş</NavLink>}
          </nav>
        </div>

        {user ? (
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 pb-4">
            <p className="text-xs text-slate-400">
              {user.first_name} {user.last_name} · {user.email}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {error ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-rose-200">Entity listesi yüklenemedi.</span>
                  <button
                    className="text-xs font-semibold text-cyan-300 hover:text-cyan-200"
                    onClick={() => void refreshEntities()}
                  >
                    Tekrar dene
                  </button>
                </div>
              ) : (
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  İşlem yapılan tüzel/gerçek kişi
                  <select
                    className="min-w-56 rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300"
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
                <NavLink className="text-xs font-medium text-cyan-300 hover:text-cyan-200" to={`/entities/${selectedEntityId}`}>
                  Profili aç
                </NavLink>
              ) : null}
            </div>
          </div>
        ) : null}
      </header>

      <main className="relative z-0 mx-auto max-w-6xl px-5 py-10">
        <Outlet />
      </main>
    </div>
  );
}
