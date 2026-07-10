# 01 — Moka Contract-Faithful Mock Server + HTTP Client (M0-M1)

> **Durum:** Ready — 2026-07-10 · **Master ref:** Moka planı §2, §4-§8, §14-§15, §21-§22, Wave M0-M1
> **Bağımlılık:** 00 (H0) merge edilmiş olmalı. DEMO ÖNCESİ uygulanır; **tamamen additive**.
> **Branch'ler:** aşağıda faz bazında → hepsi **master**'a PR
> **Sahipler:** Berke = gateway port + HTTP client + demo driver · Yusuf = contract DTO'ları + mock server + E2E contract testleri
> **Tahmin:** 2-2.5 gün (iki kişi paralel)

## Amaç

Moka United public `PaymentDealer` pool-payment contract'ının (profil: `moka_payment_dealer_pool_v1`) birebir DTO modellerini, gerçek HTTP konuşan bir client'ı ve ayrı process'te çalışan contract-faithful bir mock Moka servisini kurmak. **Ana ödeme akışına dokunulmaz**: `payment_provider.py`, `settlement.py`, `approvals.py`, `main.py` router kayıtları değişmez. Jüriye "backend'imiz Moka'nın yayımlanmış contract'ıyla gerçek HTTP JSON konuşuyor" yan-panel demosu verir; cutover 06'dadır.

## Kırmızı çizgiler (repo güvenliği)

- Mevcut `PaymentProvider` ABC ve `MockMokaProvider` **değiştirilmez**.
- `backend/mock_moka/` ana app'e import/register **edilmez**; kendi uvicorn process'i (port 8001) ve kendi DB'si (`code/data/runtime/mock_moka.db`, gitignore) vardır.
- Yeni kod yalnız yeni dosyalarda + `config.py`'ye additive Settings alanları + `requirements.txt`'e `simplejson` satırı.
- Mock, dokümante edilmemiş Moka davranışı üretmez (partial approve, capture ratio, çoklu approve YOK — Moka §3.1).

## Fazlar

### Faz 1A — Contract freeze (M0) — iki küçük paralel branch, önce Yusuf'unki merge edilir

**Yusuf — `feat/moka-contract-models`**

- `code/backend/app/services/payments/__init__.py` + `moka/contracts.py`: exact-casing Pydantic modelleri (Moka §22.1): `ApiResponse` zarfı (`Data`/`ResultCode`/`ResultMessage`/`Exception`), `PaymentDealerAuthentication`, `PaymentDealerRequest` (DoDirectPayment alan seti, `IsPoolPayment` dahil), approve/undo istekleri (`VirtualPosOrderId`/`OtherTrxCode`), detail-list istek/cevap minimumu (`PaymentStatus`/`TrxStatus`).
- `moka/errors.py`: public error-code kataloğu (Moka §2.5-2.6 listeleri) + domain error tipleri (Moka §15.1) + eşleme tablosu; bilinmeyen ResultCode → `ProviderContractViolation` (fail-closed).
- Golden JSON fixture'ları (`code/tests/fixtures/moka/*.json`) + contract snapshot testleri (alan adları/casing kilitli).

**Berke — `feat/moka-gateway-port`**

- `services/payments/ports.py`: `PaymentGateway` Protocol (Moka §6: `create_pool_payment(command)`, `approve_pool_payment(identifier)`, `undo_pool_approval(identifier)`, `get_payment_detail(query)`) — **`capture_ratio` port'ta yok**.
- `services/payments/domain.py`: `CreatePoolPaymentCommand` (amount_minor, currency, other_trx_code, description…), `ProviderPaymentIdentifier`, sonuç tipleri, `ProviderCapabilities` + `MOKA_STANDARD_PROFILE` sabiti (Moka §6.1).
- `FakePaymentGateway` (ağsız, in-memory) — 06'daki cutover'da fake yol bu port'tan geçecek.

**Freeze:** İki branch merge edilince `contracts.py` + port imzaları donar; breaking değişiklik iki taraf onayı ister.

### Faz 1B — Paralel implementasyon (M1)

**Berke — `feat/moka-http-client`**

- `moka/authentication.py`: CheckKey = lowercase-hex SHA-256(`DealerCode + "MK" + Username + "PD" + Password`) (Moka §2.3).
- `moka/serialization.py`: `amount_minor` → `Decimal/100` JSON numeric (simplejson `use_decimal=True`; snapshot testiyle kilitlenir, binary float drift yok — Moka §7.4) · currency map `TRY↔TL`, desteklenmeyen → `PROVIDER_UNSUPPORTED_CURRENCY` (Moka §7.3).
- `moka/client.py`: `MokaPaymentDealerClient` — httpx sync; connect 5s / read 20s; create/approve'da kör retry YOK, timeout → `unknown_result` (Moka §7.2); iki katmanlı hata ayrımı (envelope `ResultCode != Success` vs `Data.IsSuccessful == false`, Moka §2.2); `moka/mapper.py` ApiResponse → domain sonuçları; `moka/redaction.py` redacted trace (Password → `***`, CheckKey → `first6...last4`, CardToken → `token_****1234`).
- `config.py` additive alanlar: `payment_provider`'a `moka_http` değeri (henüz `make_payment_provider`'a BAĞLANMAZ), `moka_base_url`, `moka_dealer_code`, `moka_username`, `moka_password`, `moka_card_token`, `moka_software`, `moka_timeout_seconds`, `moka_contract_profile` + `__repr__` maskeleri (Moka §21). `.env.example` güncellenir.

**Yusuf — `feat/moka-mock-server`**

- `code/backend/mock_moka/`: bağımsız FastAPI app (`app.py`), kendi `db.py` (sqlite, WAL; `MOCK_MOKA_DB_PATH`), `config.py` (env: `MOCK_MOKA_DEALER_CODE/USERNAME/PASSWORD`, `MOCK_MOKA_VIRTUAL_POS_ENABLED`, `MOCK_MOKA_FAULTS_ENABLED`).
- Endpoint'ler (Moka §14.1): `POST /PaymentDealer/DoDirectPayment` (IsPoolPayment=1 → `dealer_payments` satırı, `VirtualPosOrderId` üretimi) · `DoApprovePoolPayment` · `UndoApprovePoolPayment` (`statement_closed=false` iken; Moka §2.6) · `GetDealerPaymentTrxDetailList` · `GetPaymentList`.
- Auth doğrulaması: missing/malformed → `InvalidRequest`, yanlış kimlik → `InvalidAccount`, pos kapalı → `VirtualPosNotFound`; CheckKey formülü doğrulanır.
- Durum eşlemesi `status_mapper.py`: pool bekliyor 0/0 · approved 2/1 · cancelled 3/1 · refunded 4/1 (Moka §2.7).
- Public error code'ları birebir (Moka §2.5-2.6); `PaymentAlreadyApproved`, `PaymentIsNotPoolPayment`, `DealerPaymentNotFound`, `OtherTrxCodeOrVirtualPosOrderIdMustGiven` dahil. **Yeni Moka kodu icat edilmez.**
- Demo token davranışı (Moka §14.4): `DEMO-TOKEN-SUCCESS` · `DEMO-TOKEN-BANK-DECLINE` (bank-level failure) · `DEMO-TOKEN-TIMEOUT-AFTER-CREATE` (yalnız `MOCK_MOKA_FAULTS_ENABLED=true`).
- `mock_operations` yalnız redacted request saklar (Password/CheckKey/CardToken persist edilmez).

### Faz 1C — Entegrasyon + demo sürücüsü

**Yusuf — `feat/moka-e2e-contract-tests`**

- `httpx.ASGITransport(mock_moka_app)` üzerinden gerçek client'la: create → parse → ID sakla → approve → ikinci approve `PaymentAlreadyApproved` → undo → detail reconcile zinciri (Moka §22.8).
- Negatifler: CheckKey yanlış, identifier'sız approve, non-pool approve, bank decline, bilinmeyen ödeme.
- Secret-leakage testleri: response/trace/log çıktılarında Password/CheckKey/CardToken/PAN yok (Moka §22.12).

**Berke — `feat/moka-demo-driver`**

- `code/scripts/demo_moka_contract.py`: CLI — `MOKA_BASE_URL`'e gerçek HTTP ile create(amount) → approve → detail; her adımda **redacted request/response JSON çiftini** stdout'a basar; `--fault` bayrağıyla decline senaryosu. Jüri gösterimi: Terminal 1 `uvicorn backend.mock_moka.app:app --port 8001`, Terminal 2 script (Moka §4.2).
- `code/backend/.env.example` + AGENTS "Pratik notlar" çalıştırma komutları.

## Kabul kriterleri

- Moka §25'ten bu faza düşenler: 1-9, 15, 17 (client aynı kodla `MOKA_BASE_URL` değişimiyle mock/sandbox'a yönelebilir — sandbox doğrulaması yapılmadığı sürece "contract-faithful mock" etiketi, Moka §26).
- Ana app'in davranışı bit-bit aynı: mevcut 214+ test, yeni dosyalar olmadan da geçtiği gibi geçer.
- Yeni testler: contract DTO snapshot + CheckKey + serializer + mock endpoint'leri + E2E zinciri + leakage.

## Kapsam dışı (bilinçli)

- `make_payment_provider`'ın `moka_http` dalı ve settlement/funding cutover'ı → **06**.
- Cancel/refund endpoint'leri, marketplace profili, webhook → 07 / ayrı plan.
- funding_units/provider_payments tabloları → 06 (package-tabanlı karar gereği).

## Doc-sync

ARCHITECTURE §3.3'e "PaymentGateway port'u + contract-faithful mock server (ayrı process)" paragrafı ve §1 dizin ağacına `services/payments/` + `backend/mock_moka/` girer; AGENTS Pratik notlar'a çalıştırma komutu eklenir. `moka_cüzdan_entegrasyonu.md` planning dosyasına "Moka contract planıyla supersede edildi" notu düşülür.
