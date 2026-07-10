# 03 — Identity, Session, Legal Entity, Ownership ve Invitation Onboarding (Program 1)

> **Durum:** Ready — 2026-07-10 · **Master ref:** v2 §2.2, §2.13, §5.1-5.7, §6, Program 1, Wave 1
> **Bağımlılık:** 02 merge + Wave-0 freeze'leri. Integration branch: `program/domain-evolution-v2`
> **Branch'ler:** Berke `feat/identity-session-entities` · Yusuf `feat/participants-invitations-audit` · entegrasyon: Berke `feat/transaction-ownership-cutover`
> **Tahmin:** 4-6 gün (paralel)

## Amaç

Anonim capability-link çekirdeğinin üstüne hesap katmanını kurmak: user/session/CSRF, legal entity + membership (şifreli TCKN/VKN), transaction sahipliği (`lifecycle_version=account_v2`), davet ile karşı taraf onboarding'i ve actor-aware audit. Legacy işlemler `LEGACY_CAPABILITY_ACCESS_ENABLED=true` (bu fazda default) ile aynen çalışmaya devam eder.

## Fazlar

### Faz 3A — Identity çekirdeği (Berke, `feat/identity-session-entities`)

Dosya sınırı: `schemas/identity.py`, `services/auth.py`, `services/identity.py`, `services/access_control.py` (session actor + membership guard implementasyonu — tek sahip Berke), `repositories/users.py`, `repositories/entities.py`, `routers/auth.py`, `routers/entities.py`, `db/migrations/003*`, `004*`.

1. **003_identity_sessions:** `users` (v2 §5.1, `UNIQUE(email_normalized)`; ek karar: `platform_role TEXT NULL` kolonu — reviewer|admin, ayrı tablo MVP'de gereksiz) + `sessions` (v2 §5.2).
2. **Auth:** `argon2-cffi` (Argon2id) parola hash'i; register/login/logout/me/sessions-revoke (§14 Auth uçları); generic login hatası; session token random 32B → DB'de SHA-256 hash; cookie HttpOnly + SameSite=Lax + prod'da Secure (env `SESSION_COOKIE_SECURE`); CSRF: login'de csrf token üretilir (cookie-okunabilir), mutating isteklerde `X-CSRF-Token` header + Origin kontrolü; `last_seen_at` yalnız >60 sn eskiyse yazılır (v2 §2.6).
3. **004_legal_entities_memberships:** v2 §5.3-5.4 + `UNIQUE(user_id, legal_entity_id)`. Tax ID koruması: `cryptography` (AESGCM) ile `tax_identifier_ciphertext`, `hmac`/stdlib ile `tax_identifier_lookup_hmac` (env `APP_ENCRYPTION_KEY`, `APP_HMAC_KEY`; `Settings.__repr__` maskeler), `last4` projection. Ham identifier hiçbir response/log/event'e girmez.
4. **Entities API:** POST/GET/GET-id/PATCH (§14); owner/admin/member yetkileri (`access_control.require_active_membership`); masked projection.
5. Demo seed: `scripts/seed_demo_users.py` (berke/yusuf + ABC A.Ş./XYZ Ltd. fixture'ları; `auth_method=demo_seed`).
6. Yeni bağımlılıklar `requirements-core.txt`'e: `argon2-cffi`, `cryptography` (Berke — integration lead).

### Faz 3B — Participants, invitations, audit (Yusuf, `feat/participants-invitations-audit`)

Dosya sınırı: `schemas/participants.py`, `services/participants.py`, `services/invitations.py`, `services/audit.py`, `services/notifications.py`, `repositories/participants.py`, `repositories/invitations.py`, `routers/participants.py`, `routers/invitations.py`, `db/migrations/005*`, `006*`.

1. **005_participants_invitations:** `transaction_participants` (v2 §5.5, `UNIQUE(transaction_id, role)`) + `transaction_invitations` (v2 §5.7; token yalnız hash'lenmiş saklanır, expiry, tek kullanım).
2. **006_audit_events:** v2 §5.21; `services/audit.py::record(conn, actor, action, target, metadata_allowlist)` — business event ile **aynı connection**'da.
3. **ParticipantService** — donmuş imzalar (v2 §8.1): `attach_creator`, `create_counterparty_placeholder` (extracted snapshot'ı extraction'dan alır), `accept_invitation` (email eşleşmesi zorunlu, creator kabul edemez, entity seç/oluştur-bağla).
4. **Invitation API** (§14): create (yalnız transaction manager/creator) · `GET /api/invitations/{token}/preview` (auth'suz güvenli önizleme: taraf rolü + işlem başlığı, PII yok) · accept (login zorunlu; consumed) · revoke.
5. **Participant API** (§14): list · `PUT participants/me/profile` (declared snapshot) · `POST participants/me/confirm` (confirmed snapshot + `confirmed_at`).
6. **NotificationProvider** port + `FakeNotificationProvider` (linki döndürür/loglar — adapter+fake ilkesi).
7. Conflict kuralları (v2 §6.3): aynı entity iki taraf olamaz; creator kendi davetini kabul edemez — service içinde, testli.
8. **3A'dan bağımsızlık:** 3B, auth iç yapısını (session/user repository) import etmez; yalnız 02'de donmuş `get_current_actor` + `require_active_membership` imzalarını çağırır. API testleri 3A merge'ini beklemez: `app.dependency_overrides[get_current_actor] = stub_actor` ile koşar; gerçek session'lı uçtan uca doğrulama 3C gate'indedir. Taraf-özel yetki kuralları Yusuf'un kendi servis modüllerinde yaşar; `access_control.py`'ye Yusuf dokunmaz (harita sahiplik tablosu).

### Faz 3C — Transaction ownership cutover (Berke, `feat/transaction-ownership-cutover`; 3A+3B merge SONRASI)

1. **007_transaction_lifecycle_v2:** `transactions`'a additive kolonlar: `created_by_user_id`, `owner_entity_id`, `lifecycle_version` (`legacy_v1` backfill / yeni satırlar `account_v2`), `content_sha256`.
2. `POST /api/transactions`: **auth zorunlu** (session) — multipart `file + acting_entity_id + own_role + counterparty_email?` (§14). Upload anında bytes SHA-256 hesaplanır (v2 §2.11'in hash yarısı; storage 04'te). `ParticipantService.attach_creator` + placeholder + (email verildiyse) invitation çağrılır. Capability token üretimi account işlemlerde **durur** (party erişimi assignment/participant üzerinden); legacy işlemler token'larıyla yaşar.
3. List/detail scoping: authenticated user yalnız üyesi/katılımcısı olduğu işlemleri görür; `DEMO_PUBLIC_DASHBOARD` yalnız legacy demo listesini açar. Party-view/manager-view/approvals/delivery legacy uçları `LEGACY_CAPABILITY_ACCESS_ENABLED` (default **true** bu fazda) arkasında aynen çalışır.
4. Legacy state adapter (02'deki kontrat) detail cevabına `canonical_state` alanı ekler (v2 §2.8 tablosu); mevcut `state` alanı değişmeden kalır.

## Donmuş interface

`ParticipantService` (v2 §8.1) — 3B başında imzalar PR ile donar; 3C yalnız bu imzaları çağırır.

## Paralellik ve merge sırası

3A ∥ 3B (dosya kesişimi yok; `main.py` router kayıtları Berke'de). Sonra 3C. **3C sırasında Yusuf boş beklemez:** 3A merge'iyle auth uçları hazır olduğundan 08/Faz 8A'ya (frontend foundation) başlar (harita §7). Gate senaryosu (v2 Wave 1): register → entity → authenticated upload → creator participant → invite → karşı taraf register → accept → profile confirm. **NEEDS_REVIEW bu fazda hâlâ çıkmaz sokaktır (bilinçli, v2 §2.16)** — E2E fixture'ları PASS sözleşme kullanır.

## Repo güvenliği

Tüm migration'lar additive; legacy akış default açık; mevcut senaryo testleri legacy fixture ile yeşil kalır (v2 §2.2 — fixture cutover'ı 04'ün sonundadır). Auth'suz create'in 401 dönmesi tek kırıcı değişikliktir ve mevcut testlerde create çağrıları legacy-factory helper'ına (DB'ye doğrudan legacy satır yazan test fixture'ı, Yusuf) taşınarak karşılanır.

## Kabul kriterleri

v2 Program 1 listesi birebir; ek olarak: cookie flag'leri/CSRF/last_seen-throttle testleri; tax ID ciphertext≠plaintext + HMAC lookup + masked projection testleri; invitation yanlış-email/expired/reused/revoked testleri; audit satırında actor_user/entity + request_id; IDOR: ilgisiz user'ın list/detail/participant uçlarından 403/404 alması.

## Doc-sync

ARCHITECTURE §1 (yeni servis/router'lar), §4.1 (auth/entities/invitations/participants uçları + create'in yeni imzası), §5 (yeni tablolar + lifecycle_version), §6 (6.6 "taraf kimliği = token" kuralının "legacy geçiş aracı"na indirgenmesi — v2 §2.2 referanslı); AGENTS özet + Pratik notlar (seed script).
