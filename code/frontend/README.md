# M4Trust Frontend — Faz 8A Foundation

React + Vite + TypeScript + Tailwind + React Router tabanı. Bu PR yalnız Plan 08 Faz 8A kapsamındadır: auth/session, merkezi API client, acting-entity seçimi ve legal entity create/profile ekranları. Transaction, invitation ve sonraki dikey dilim ekranları kapsam dışıdır.

## Gereksinimler

- Node.js 22
- npm 10+
- Python 3.12 backend ortamı

## Backend'i başlatma

Repo kökünden:

```bash
cd code
cp backend/.env.example .env
```

Entity create/profile akışının çalışması için `code/.env` içinde en az şu iki değer üretilmelidir:

```text
APP_ENCRYPTION_KEY=<base64 32-byte key>
APP_HMAC_KEY=<base64 key>
```

Yerel HTTP geliştirmede:

```text
SESSION_COOKIE_SECURE=false
```

Ardından:

```bash
./.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend'i başlatma

Ayrı terminalde:

```bash
cd code/frontend
npm install
npm run dev
```

Arayüz varsayılan olarak `http://127.0.0.1:5173` adresindedir.

## Frontend env ve proxy

Frontend için zorunlu env yoktur. Opsiyonel örnek:

```bash
cp .env.example .env.local
```

`VITE_BACKEND_URL` tanımlanmazsa Vite, `/api` isteklerini `http://127.0.0.1:8000` adresine proxy eder. Tarayıcı açısından istekler aynı origin'den gidiyormuş gibi görünür; backend static serving bu PR'ın kapsamında değildir.

## Cookie, session ve CSRF

- Bütün API istekleri `credentials: "include"` kullanır.
- Login yanıtı `m4t_session` HttpOnly session cookie'sini ve JS-okunabilir `m4t_csrf` cookie'sini set eder.
- CSRF korumalı mutation'larda client `m4t_csrf` değerini `X-CSRF-Token` header'ına yazar.
- Seçilen legal entity, backend membership doğrulamasına tabi `X-Acting-Entity-ID` header'ı ile gönderilir.
- Auth token localStorage/sessionStorage'a yazılmaz. LocalStorage'da yalnız hassas olmayan seçili entity id'si tutulur.
- Query token kalıcı authentication için kullanılmaz.

## Komutlar

```bash
npm run lint
npm run typecheck
npm run test
npm run build
npm run preview
```

`npm run preview` yalnız production build'i yerelde servis eder; backend proxy'si `npm run dev` yapılandırmasındadır.

## Hata davranışı

Merkezi client standart `{code, message, request_id, detail?}` zarfını typed olarak doğrular. Standart olmayan `HTTPException`, FastAPI validation veya geçersiz JSON gövdeleri ham biçimde kullanıcıya gösterilmez.

- `401` → session-required ekranı
- `403` → permission ekranı
- `409` → çözüm adımlı conflict ekranı
- network / invalid JSON → güvenli generic hata

## Görsel doğrulama

Build ve statik kontroller görsel doğruluk kanıtı değildir. Browser/preview üzerinde ayrıca kontrol yapılmadıkça screenshot veya pixel-level doğrulama iddiası yapılmamalıdır.
