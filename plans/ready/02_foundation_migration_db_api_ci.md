# 02 — Foundation: Migration Runner, DB Lifecycle, API Contract, CI (Program 0)

> **Durum:** Ready — 2026-07-10 · **Master ref:** v2 §2.4-2.6, §2.9-2.10, Program 0, Wave 0
> **Bağımlılık:** 00+01 master'da; DEMO SONRASI ilk iş. Bu planla `program/domain-evolution-v2` integration branch'i master'dan açılır.
> **Branch'ler:** Berke `feat/foundation-db-migrations` · Yusuf `feat/foundation-api-ci-contracts` → program branch'ine PR
> **Tahmin:** 2-3 gün (paralel)

## Amaç

İki kişinin güvenle paralel feature geliştirebileceği zemini kurmak: versiyonlu migration altyapısı (mevcut DB'leri bozmayan stamping ile), tek tip DB bağlantı yaşam döngüsü, ortak API hata zarfı + request-id, ActorContext/access-control kontratı, hafif CI. **Kullanıcı davranışı değişmez** — bu plan sonunda API'nin dışarıdan görünüşü bugünküyle aynıdır.

## Fazlar

### Faz 2A — DB paketi + migration runner (Berke, `feat/foundation-db-migrations`)

1. `db.py` → paket bölünmesi: `backend/app/db/connection.py` (mevcut `connect()`; H0'daki timeout/busy_timeout burada merkezileşir) · `db/migrate.py` (runner) · `db/migrations/` (sıralı `NNN_isim.py|sql` dosyaları) · `db/__init__.py` **geriye uyumlu shim**: `connect/init_db/get_db` aynı adlarla export edilir, hiçbir mevcut import kırılmaz (`init_db` artık runner'ı çağırır).
2. `001_baseline_current_schema`: bugünkü `init_db()` çıktısının TAMAMI (7 tablo + `manager_token` kolonu) — v2 §2.4; ayrı 002 tracking migration'ı yok.
3. Bootstrap/stamping algoritması (v2 §2.5, §15.2): `schema_migrations` varsa pending uygula · DB boşsa hepsini uygula · **legacy fingerprint** eşleşiyorsa (zorunlu tablo/kolon seti + `manager_token` + `tracking_policies` kolonları) 001'i "applied" olarak stamp'le ve 002+'dan devam et · tanınmayan şemada `UnknownLegacySchemaError` ile **fail-closed**, hiçbir mutasyon yapma. Stamping veri üretmez, tablo yaratmaz, baseline SQL'i çalıştırmaz.
4. Bağlantı yaşam döngüsü (v2 §2.10): request-scoped `get_db` dependency (open → yield → success commit → exception **rollback** → close); router'lardaki manuel `connect(settings)` çağrıları bu dependency'ye taşınır (davranış birebir; en riskli dosya `transactions.py` — tek PR'da, testler yeşilken). Background task'lar için `open_background_connection(settings)` helper'ı. `BEGIN IMMEDIATE` destekli kısa transaction context-manager'ı (`db/tx.py`).
5. `transactions.py` repository seam hazırlığı: `repositories/transactions.py` (`load_transaction`, liste/detay sorguları) — router davranışı değişmeden sorgular taşınır. (Not: `extracted_rules` latest-by-rowid kopyaları 04'te `rule_sets` repository'sine taşınacak; burada yalnız transactions.)
6. Migration smoke testleri: boş DB · mevcut legacy DB (fixture: bugünkü `_SCHEMA` ile kurulmuş dosya) · zaten migrate edilmiş DB (idempotent ikinci koşu) · bilinmeyen şema (fail-closed) · kesintili koşu (yarıda kalan migration tekrar koşulabilir).

### Faz 2B — API contract + CI (Yusuf, `feat/foundation-api-ci-contracts`)

1. **Hata zarfı:** `api/errors.py` **modülü** — handler fonksiyonları + yeni standart `{code, message, request_id, detail?}`. Mevcut 409 gövdeleri (`{code, message, conflicts}`) ve mevcut 403/404 string detail'leri **davranış değiştirmeden** korunur (regression); zarf yalnız yakalanmamış hatalar + bundan sonraki yeni uçlar için bağlayıcıdır. App'e kayıt Yusuf'ta DEĞİL — Berke'nin integration commit'inde (`main.py` Berke'de, harita Revizyon #3).
2. **Request-ID middleware:** `middleware/request_id.py` **modülü** — her cevapta `X-Request-ID`; log/audit contract'ına girer. App'e kayıt yine Berke'nin integration commit'inde.
3. **ActorContext + access-control kontrat testleri:** `services/access_control.py`'nin **sahibi Berke'dir** (2A'ya ek küçük kalem; dosya 03'te session actor'ıyla dolacağı için tek sahip): ActorContext dataclass'ı, `get_current_actor` FastAPI dependency imzası ve `require_*` imzaları; bu fazda yalnız `anonymous`/`legacy_capability` actor'ları üretilir (davranış değişmez). İmzalar **frozen** — Yusuf bu maddede yalnız kontrat testlerini yazar; 03/3B testlerde `dependency_overrides` + StubActor ile bu imzalara karşı kodlar.
4. **Business event / audit event ayrım kontratı:** kısa doküman + `services/audit.py` iskelet imzası (tablo 006'da, Yusuf 03'te yazar). Kural: aynı connection/transaction'da yazılır.
5. **Requirements manifest ayrımı** (v2 §2.9): `requirements-core.txt` (fastapi, pydantic, uvicorn, python-multipart, httpx, simplejson, parser hafif deps) · `requirements-ci.txt` (core + pytest + lint) · `requirements-rag.txt` (chromadb, FlagEmbedding) · `requirements-video.txt` (opencv, requests) · `requirements.txt` → hepsini include eden şemsiye. **Dosya sahibi Berke olduğundan bu madde Berke onaylı tek commit'tir.**
6. **GitHub Actions CI** (`.github/workflows/backend-ci.yml`): push/PR'da `pip install -r requirements-ci.txt` + `pytest -q` (Python 3.12, pip cache). Ağır RAG/torch kurulmaz; RAG/video testleri zaten import-guard'lı/fake ile geçiyor (bugün venv'de chromadb yokken 214 yeşil — doğrulandı).
7. **Test helper standardizasyonu:** `tests/conftest.py`'ye ortak `isolated_db` + `client` fixture'ları (bugün test dosyalarında kopyalanan autouse fixture'lar tekilleştirilir; test davranışı aynı). Bu andan itibaren `conftest.py`'nin tek sahibi Yusuf'tur; domain fixture'ları herkes kendi ayrı modülünde tutar.
8. **Legacy state adapter kontratı (v2 §2.8) — Berke'nin 02 yükünü dengelemek için 2B'de:** `services/transaction_state.py` — `lifecycle_version` kavramı + legacy→canonical projection tablosu, saf fonksiyon + tablo-testleri (kolon migration'ı 007'de). Kontrat 02 sonunda donar; **implementasyon sahipliği 03'ten itibaren Berke'ye geçer** (3C ve 06 doldurur) — donmuş kontratta çapraz-yazarlık güvenlidir.

## Paralellik ve merge sırası

2A ve 2B dosya kesişimi iki bilinçli istisna dışında yok: requirements manifestleri ve `main.py` kayıtları (middleware/handler registration) — ikisi de **Berke'nin integration commit'idir**, Yusuf yalnız modül üretir. Merge sırası: **2A önce** (get_db dependency'si), 2B rebase edip üstüne, en son Berke'nin main.py wiring commit'i. Wave sonunda freeze: ActorContext · `get_current_actor` · `require_authenticated_user`/`require_active_membership` imzaları · error envelope · `get_db` · migration contract (v2 Wave 0 gate). **Bu gate geçmeden 03 branch'leri açılmaz.**

## Kabul kriterleri (v2 Program 0 listesi + somutlar)

- Boş DB tüm migration'ları alır; mevcut runtime DB fingerprint'le stamp'lenir; bilinmeyen şema mutate edilmez; ikinci koşu idempotent.
- Router'lar tek `get_db` dependency'sinden geçer; exception'da rollback testi yeşil.
- CI, PR'da ağır bağımlılık kurmadan full suite koşar ve yeşildir.
- Dış API davranışı değişmemiştir: mevcut 214+ test **değişiklik gerektirmeden** geçer (test helper tekilleştirmesi hariç mekanik dokunuş yok).
- `ExtractionJSON`, decision/tracking semantiği değişmez.

## Kapsam dışı

Kullanıcıya görünür hiçbir yeni özellik; auth; yeni tablo (001 baseline hariç); response modellerinin mevcut uçlara uygulanması (uçlar 03+'ta elden geçtikçe modellenir).

## Doc-sync

ARCHITECTURE §1 (db/ paketi, repositories/), §2 stack (CI, manifest ayrımı), §5 (migration runner + stamping paragrafı — mevcut "init_db additive" anlatısının yerini alır); AGENTS Pratik notlar (test/CI komutları).
