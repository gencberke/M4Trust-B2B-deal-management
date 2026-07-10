# 08 — Frontend Vertical Slices (Program 6)

> **Durum:** Ready — 2026-07-10 · **Master ref:** v2 §2.13, Program 6 · Moka §20 (trace panel)
> **Bağımlılık:** Slice 1 için 03; sonraki slice'lar ilgili backend programı bittikçe. **03'ten itibaren backend programlarıyla PARALEL yürüyebilir** (contract frozen olduğu sürece) — Yusuf'un Wave'lerdeki "frontend consumer" opsiyonu budur.
> **Branch'ler:** Yusuf lead — `feat/frontend-foundation`, sonra `feat/ui-slice-N-*` · Berke: proxy/serve config + review
> **Tahmin:** slice başına 1-2 gün

## Amaç

`code/frontend/` (bugün boş — yalnız README) altına React+Vite+Tailwind SPA'yı kurup account akışını dikey dilimlerle görünür yapmak. Her slice tek başına demolanabilir; frontend hiçbir iş kuralı içermez (readiness/permission bilgisi backend projection'larından okunur).

## Temel kurallar (v2 §2.13, Program 6)

- Dev: Vite `/api` proxy → FastAPI (same-origin görünümü); prod: SPA statik + API same-origin. `fetch(..., credentials="include")` + `X-CSRF-Token` header'ı merkezi API client'ta.
- Query-token kalıcı auth olarak KULLANILMAZ (yalnız legacy link görünümleri ve invitation preview).
- Hata zarfı (`{code, message, request_id}`) merkezi handle edilir; `source_quote` yalnız yetkili görünümlerde.
- ARCHITECTURE §1'deki frontend dizin hedefi (api/ · pages/ · components/) korunur.

## Fazlar / Slice'lar

### Faz 8A — Foundation (Yusuf, `feat/frontend-foundation`; 03 sonrası başlar)

Vite+React+Tailwind scaffold · router · merkezi API client (proxy, credentials, CSRF, error envelope) · auth sayfaları (register/login/logout/me) · acting-entity selector + entity profil formu (masked tax-id gösterimi). `code/frontend/README` güncellenir; `npm run dev` + backend tek komut dokümante edilir.

### Slice 2 — İşlem + davet (03 bitince): authenticated upload (dosya + entity + rol + counterparty email) · işlem listesi/detayı (scoped; `canonical_state` rozeti) · davet gönder/preview/accept/onboarding akışı · participant profil doldur/confirm ekranı.

### Slice 3 — Kurallar + review (04 Wave A bitince): extracted vs declared taraf diff'i · rule-set version listesi + diff · validator/review bulguları paneli · rule revision formu (yeni version + re-validate) · review action'ları.

### Slice 4 — Policy + ratification (04 bitince): tracking policy seçim/kilit ekranı (mevcut manager-view'un account'lu hali) · ratification package görünümü: **package hash + funding schedule (unit/tranche tablosu) + release_mode** iki tarafa aynı projection · "Entity adına onayla" aksiyonu · superseded package uyarısı.

### Slice 5 — Milestone + kanıt + dispute (05-06 bitince): milestone/funding-unit zaman çizelgesi (pool_created/approved rozetleri) · e-irsaliye/video kanıt yükleme (yetkili aktör) · review/dispute paneli (insan dispute açma, action timeline).

### Slice 6 — Audit + ödeme + Moka trace (07 bitince): evidence-bundle görüntüleme + snapshot alma · ödeme durumu (instruction/attempt listesi, reconcile butonu) · **Moka API Trace paneli** (Moka §20: redacted request/response çiftleri, "public contract simulation" rozeti) · demo senaryo kılavuzu/ekran kayıtları.

## Paralellik

Yusuf slice'ları backend wave'lerinin arasına serpiştirir (v2 Wave 6 Track B seçeneği); Berke yalnız `vite.config` proxy + prod serve (FastAPI static mount veya ayrı serve kararı) + PR review. Frontend branch'leri backend branch'leriyle dosya kesişmez → merge riski yok.

## Repo güvenliği

Frontend eklemek backend'i etkilemez; CI'a ayrı hafif job (lint+build) eklenir, backend suite'e dokunulmaz. Her slice kendi PR'ı.

## Kabul kriterleri

Her slice için: ilgili v2 Program 6 ekranı çalışır + hata durumları (401/403/409) kullanıcıya zarif gösterilir + hiçbir response'ta olmayan veri UI'da türetilmez. Program sonunda v2 §20 kabul senaryosunun 1-27 adımları tarayıcıdan yürütülebilir.

## Doc-sync

ARCHITECTURE §1 frontend dizini + route listesi güncellenir (mevcut `/t/:id/party?token` route'ları legacy olarak işaretlenir); AGENTS repo düzeni satırı.
