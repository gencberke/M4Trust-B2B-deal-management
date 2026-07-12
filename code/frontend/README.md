# M4Trust Frontend — Faz 8A + 8B1/8B2

React + Vite + TypeScript + Tailwind + React Router tabanı. Faz 8A auth/session ve tüzel kişi temelini; Faz 8B1 authenticated `account_v2` işlem çekirdeğini; Faz 8B2 ise kural inceleme/revizyonu, takip politikası, değişmez onay paketi ve çift taraflı ratifikasyonu sağlar. Teslimat/ödeme (8C) ekranları sonraki PR'dadır.

## Faz 8B rotaları

- `/transactions` — yalnız taraf/yönetici olduğunuz işlemlerin listesi.
- `/transactions/new` — sözleşme yükleme + `account_v2` işlem oluşturma (multipart; başarıda tek seferlik davet bağlantısı).
- `/transactions/:id` — detay kabuğu; `overview`'e yönlenir. Bölümler: `overview` (durum, redacted extraction özeti, validator, event timeline, takılı extraction retry), `parties` (katılımcılar, davet paneli, kendi profil/onay), `rules` (taraf karşılaştırma, validator/review kayıtları, değişmez sürüm/diff, revizyon ve revalidation) ve `ratification` (takip politikası, paket hash'i/takvim, taraf onay ilerlemesi ve ratify).
- `/invitations/:token` — public davet önizlemesi + giriş yapılınca kabul. Davet token'ı yalnız bu rotada taşınır; başka hiçbir yere yazılmaz/loglanmaz.

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

## Test stratejisi

Varsayılan test ortamı **node**'dur ve `src/**/*.test.ts` saf yardımcı/api testlerini kapsar (8A deseni; mock `fetch`). 8B1 ile davranışsal (DOM) kapsama için küçük bir katman eklendi: `src/**/*.test.tsx` dosyaları dosya başındaki `// @vitest-environment jsdom` yorumuyla jsdom'a geçer (node testleri değişmez). Yalnız **dev bağımlılığı** eklendi (`jsdom`, `@testing-library/react`, `@testing-library/user-event`); hiçbir yeni runtime bağımlılığı yoktur. Global cache/state framework'ü (react-query/Redux vb.) bilinçli olarak kullanılmaz — okuma başına ≤2 istek, mutation sonrası ilgili `refresh()` yeterlidir.

## Faz 8B1 manuel duman testi (özet)

Ön koşul: `code/.env` içinde `APP_ENCRYPTION_KEY`, `APP_HMAC_KEY`, `SESSION_COOKIE_SECURE=false`; tek worker uvicorn; `python scripts/seed_demo_users.py` ile Berke/Yusuf + ABC A.Ş./XYZ Ltd. seed'i; `VIDEO_PROVIDER=fake`.

1. Berke ile giriş, ABC A.Ş. seç → `/transactions` boş durum.
2. `/transactions/new`: küçük `.md` sözleşme yükle, rol alıcı, karşı taraf = Yusuf'un e-postası → tek seferlik `/invitations/{token}` bağlantısı.
3. Detay `overview`: `uploaded/extracting` (4 sn polling) → `awaiting_approval`; extraction özeti + validator + timeline.
4. `parties`: iki katılımcı; davet paneli (revoke); profil kaydet → `ready`; onayla → `confirmed` (tekrar düzenleme 409 mesajı).
5. İkinci profil/tarayıcıda davet bağlantısını çıkışlıyken aç → yalnız önizleme; Yusuf ile giriş, XYZ Ltd. seç, kabul → `parties`; adres çubuğundan token kaybolur.
6. Güvenlik: localStorage yalnız `m4t_acting_entity_id`; preview/accept dışında hiçbir istek token taşımaz; DOM'da `tax_id`/`source_quote` yok.

## Hata davranışı

Merkezi client standart `{code, message, request_id, detail?}` zarfını typed olarak doğrular. Standart olmayan `HTTPException`, FastAPI validation veya geçersiz JSON gövdeleri ham biçimde kullanıcıya gösterilmez.

- `401` → session-required ekranı
- `403` → permission ekranı
- `409` → çözüm adımlı conflict ekranı
- network / invalid JSON → güvenli generic hata

## Görsel doğrulama

Build ve statik kontroller görsel doğruluk kanıtı değildir. Browser/preview üzerinde ayrıca kontrol yapılmadıkça screenshot veya pixel-level doğrulama iddiası yapılmamalıdır.
