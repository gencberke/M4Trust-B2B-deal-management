# 00 — Teslimat Kanıtı Yetkilendirme Hotfix'i (H0)

> **Durum:** Ready — 2026-07-10 · **Master ref:** v2 §3 (H0), §2.6 (busy_timeout)
> **Bağımlılık:** yok — programdan bağımsız, DEMO ÖNCESİ uygulanır.
> **Branch:** `hotfix/h0-delivery-authorization` → **master**'a PR
> **Sahipler:** Berke = implementasyon · Yusuf = güvenlik regression testleri (aynı branch'e ayrı commit'ler; Berke impl'i push'ladıktan sonra Yusuf test commit'leri)
> **Tahmin:** toplam ~1 gün

## Amaç

Bugün canlı olan anonim uçtan uca release kombinasyonunu kapatmak: `GET /api/transactions` auth'suz tüm işlem id'lerini veriyor ([transactions.py:251](../../code/backend/app/routers/transactions.py)) ve `POST /{id}/events/e-irsaliye` + `POST /{id}/delivery-video` hiçbir token istemiyor ([delivery.py:129,147](../../code/backend/app/routers/delivery.py)). İkisinin birleşimi, id'yi listeden alan herkesin `delivered_quantity` gönderip mock release tetiklemesine izin veriyor. Ayrıca SQLite `busy_timeout` ve iki bayat doküman düzeltilir.

## İş kalemleri

### A. Delivery uçlarına capability guard (Berke)

- Her iki delivery ucu `token` **query parametresi** alır (party-view/evidence ile aynı desen; body şemaları değişmez).
- Kabul: **seller token VEYA manager token**. Buyer token → 403 (alıcı kendi lehine teslim kanıtı süremez, v2 §3). Token yok/yanlış → 403.
- Guard, `_guard_evidence_channel`'dan ÖNCE çalışır (önce kimlik, sonra kanal/state).
- Token hiçbir event payload'ına, log'a ve evidence bundle'a yazılmaz (mevcut §6.8 kuralı korunur — `body.model_dump()` token içermediği için e-irsaliye payload'ı temiz kalır; video analiz payload'ı zaten token taşımıyor; test ile kilitlenir).

### B. Public liste env kapısı (Berke)

- `Settings`'e `demo_public_dashboard: bool` (env `DEMO_PUBLIC_DASHBOARD`, default **false**).
- `GET /api/transactions`: env false iken **403** (`{"detail": "Liste erişimi kapalı."}`). Env true iken bugünkü davranış.
- `GET /api/transactions/{id}` DEĞİŞMEZ (id artık listeden sızmadığı için pratik capability sırrı haline gelir; hesap tabanlı scoping Program 03'ün işi).
- `code/backend/.env.example`'a `DEMO_PUBLIC_DASHBOARD=true` satırı + "demo günü açılır" notu.

### C. SQLite dayanıklılık (Berke)

- `db.connect()`: `sqlite3.connect(..., timeout=5.0)` + `PRAGMA busy_timeout=5000` (v2 §2.6). Başka PRAGMA değişikliği yok.

### D. Doküman bayatlığı (Berke)

- [approvals.py](../../code/backend/app/routers/approvals.py) docstring'inden kapatılmış `awaiting_review` bypass ifadesi çıkarılır.
- AGENTS.md test sayısı 209 → 214 güncellenir.

### E. Güvenlik regression testleri (Yusuf)

Yeni dosya `code/tests/test_delivery_authorization.py`:

- anonymous e-irsaliye → 403 · buyer token → 403 · seller token → 200 · manager token → 200
- anonymous video → 403 · seller/manager video → kabul
- token'ın events/evidence bundle çıktısında bulunmadığı (bundle string taraması)
- `DEMO_PUBLIC_DASHBOARD` unset → liste 403; true → 200
- karar semantiği değişmedi: seller token'lı tam teslim → `capture` (mevcut akış)

Mevcut testlerin uyarlanması (Yusuf): liste kullanan testlere `monkeypatch.setenv("DEMO_PUBLIC_DASHBOARD", "true")` (autouse fixture'a eklenebilir); delivery çağrılarına seller token parametresi.

## Repo güvenliği

- Şema değişikliği yok, migration yok, event zarfı değişmez, `ExtractionJSON` değişmez.
- Karar/settlement yoluna dokunulmaz — yalnız uçların önüne guard gelir.
- Demo akışı: `.env`'e `DEMO_PUBLIC_DASHBOARD=true` yazılarak birebir korunur.

## Kabul kriterleri

- v2 §3 H0 kabul listesi birebir + full suite yeşil (214 + yeni testler).
- `curl` ile anonim liste ve anonim/buyer e-irsaliye 403 doğrulanır.

## Doc-sync

ARCHITECTURE §4.1 tablosunda iki delivery satırına "token (seller|manager) zorunlu, aksi 403" ve liste satırına "DEMO_PUBLIC_DASHBOARD kapısı" işlenir; AGENTS Pratik notlar'a tek satır H0 kaydı düşülür. Bu plan `done/`'a taşınırken durum bloğu işlenir.
