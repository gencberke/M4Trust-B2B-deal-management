import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiClientError, toApiClientError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Notice, PageHeading } from "../components/Feedback";
import type { LoginRequest, RegisterRequest } from "../types/api";
import { buttonClass, FormError, Info, inputClass } from "./shared";

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState<RegisterRequest>({ email: "", password: "", first_name: "", last_name: "" });
  const [error, setError] = useState<ApiClientError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await register(form);
      navigate("/login", { replace: true, state: { registered: true } });
    } catch (caught) {
      setError(toApiClientError(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <PageHeading title="Hesap oluştur" description="Kayıt işlemi oturum açmaz; tamamlandıktan sonra giriş ekranına yönlendirilirsiniz." />
      <form className="space-y-4 rounded-3xl border border-white/10 bg-white/5 p-6" onSubmit={submit}>
        <div className="grid gap-4 sm:grid-cols-2">
          <input className={inputClass} required placeholder="Ad" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <input className={inputClass} required placeholder="Soyad" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
        </div>
        <input className={inputClass} required type="email" placeholder="E-posta" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <input className={inputClass} required minLength={8} type="password" placeholder="Parola · en az 8 karakter" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <FormError error={error} />
        <button className={buttonClass} disabled={submitting}>{submitting ? "Kaydediliyor…" : "Kayıt ol"}</button>
      </form>
    </div>
  );
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState<LoginRequest>({ email: "", password: "" });
  const [error, setError] = useState<ApiClientError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const registered = Boolean((location.state as { registered?: boolean } | null)?.registered);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(form);
      navigate("/", { replace: true });
    } catch (caught) {
      setError(toApiClientError(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <PageHeading title="Oturum aç" description="Session HttpOnly cookie ile, CSRF doğrulaması ayrı JS-okunabilir cookie ile yürütülür." />
      <form className="space-y-4 rounded-3xl border border-white/10 bg-white/5 p-6" onSubmit={submit}>
        {registered ? <Notice tone="success">Hesabınız oluşturuldu. Şimdi giriş yapabilirsiniz.</Notice> : null}
        <input className={inputClass} required type="email" placeholder="E-posta" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <input className={inputClass} required type="password" placeholder="Parola" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <FormError error={error} />
        <button className={buttonClass} disabled={submitting}>{submitting ? "Giriş yapılıyor…" : "Giriş yap"}</button>
      </form>
    </div>
  );
}

export function LogoutPage() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<ApiClientError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleLogout() {
    setSubmitting(true);
    setError(null);
    try {
      await logout();
      navigate("/login", { replace: true });
    } catch (caught) {
      setError(toApiClientError(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <PageHeading title="Oturumu kapat" description="Mevcut session backend’de revoke edilir ve session/CSRF cookie’leri temizlenir." />
      <div className="space-y-4 rounded-3xl border border-white/10 bg-white/5 p-6">
        <FormError error={error} />
        <button className={buttonClass} disabled={submitting} onClick={() => void handleLogout()}>{submitting ? "Çıkış yapılıyor…" : "Güvenli çıkış yap"}</button>
      </div>
    </div>
  );
}

export function MePage() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <PageHeading title="Hesabım" description="Bu alan yalnız `/api/auth/me` yanıtındaki projection’ı gösterir." />
      <dl className="grid gap-4 rounded-3xl border border-white/10 bg-white/5 p-6 sm:grid-cols-2">
        <Info label="Ad soyad" value={`${user.first_name} ${user.last_name}`} />
        <Info label="E-posta" value={user.email} />
        <Info label="Durum" value={user.status} />
        <Info label="Platform rolü" value={user.platform_role ?? "Atanmamış"} />
        <Info label="E-posta doğrulama" value={user.email_verified_at ?? "Henüz doğrulanmamış"} />
        <Info label="Oluşturulma" value={user.created_at} />
      </dl>
    </>
  );
}
