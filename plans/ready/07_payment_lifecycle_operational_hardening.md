# 07 — Payment Lifecycle: Retry, Reconciliation, Undo, Processing Jobs, Trace (Program 5)

> **Durum:** Ready — 2026-07-10 · **Master ref:** v2 Program 5 · Moka §11.5-11.6, §16, §20 (payment_attempts tablosu Moka `provider_operations` ile SUPERSEDED — harita §4)
> **Bağımlılık:** 06 tamam. Integration branch: `program/domain-evolution-v2`
> **Branch'ler:** Berke `feat/payment-reconciliation-jobs` · Yusuf `feat/payment-failure-review-and-faults`
> **Tahmin:** 4-5 gün (paralel)

## Amaç

06'da kurulan funding-unit ödeme yolunu operasyonel olarak dayanıklı yapmak: unknown-outcome reconciliation'ı ürünleştirmek, güvenli retry, yetkili-insan undo/refund aksiyonları, background job kayıtları (extraction + funding + release) ve jüri/denetçi için redacted Moka API trace ucu.

## Fazlar

### Faz 7A — Reconciliation + retry + jobs + trace (Berke, `feat/payment-reconciliation-jobs`)

Dosya sınırı: `services/payments/reconciliation.py`, `services/processing_jobs.py`, `routers/payment_ops.py`, `db/migrations/018*`, `main.py` (startup recovery hook).

1. **Reconciliation servisi** (Moka §16): `reconcile_funding_unit` — `pool_creation_unknown`/`approval_unknown`/`PaymentAlreadyApproved` durumlarında `GetDealerPaymentTrxDetailList(OtherTrxCode)` → bulundu-pending → `pool_created` · bulundu-approved → success-equivalent bind · bulunamadı → kontrollü retry (aynı OtherTrxCode) · belirsiz → review case. Uç: `POST /api/transactions/{id}/payments/reconcile` (demo: explicit buton — Moka §16.4; yetki: manager/platform reviewer).
2. **Retry:** `POST /api/release-instructions/{id}/retry` — yeni instruction DEĞİL yeni `provider_operations` attempt'i (attempt_no artar, idempotency_key aynı); yalnız `failed|unknown` durumda; SQLite lock dışı business hataları retry edilmez (v2 §2.6).
3. **Undo/refund (insan aksiyonu, DAR yetki):** para hareketini tersine çeviren aksiyonlar (**undo_approval / refund**) yalnız **platform reviewer** tarafından — veya iki tarafın approver'ının aynı resolution kaydını onayladığı **bilateral resolution** ile — yürütülür. Transaction manager ticari bir tarafın kullanıcısı olabileceğinden tek başına tersine çevirme YAPAMAZ; yalnız `undo_request` review case'i açar. `PaymentGateway.undo_pool_approval` (Moka §11.6: otomatik approve→undo YOK); mock'ta `statement_closed=true` davranışı test-only fault olarak review'a düşer (Moka §2.6). Refund aynı kalıpla `refund` operation'ı olarak eklenir (gateway'e `refund_payment` + mock endpoint'i — contracts.py değişikliği iki taraf onaylı ortak PR). **Reconcile ucu manager'a açık kalır:** yalnız durum senkronizasyonudur, para hareketi üretmez.
4. **018_processing_jobs:** v2 Faz 5G — job kayıtları (`kind: extraction|funding|release|reconcile`, attempt count, last_error, durum); pipeline/funding/release çağrıları job kaydı altında koşar; **startup recovery**: `extracting`te takılı işlemler ve `*_unknown` unit'ler açılışta işaretlenir/yeniden kuyruklanır (process ölümü artık kalıcı takılma üretmez).
5. **Trace ucu** (Moka §20): `GET /api/transactions/{id}/payment-trace` — yalnız yetkili manager/reviewer; `provider_operations`'tan endpoint/timestamp/OtherTrxCode/VirtualPosOrderId/amount/redacted request/exact response/ResultCode/mapped status listesi. Password/CheckKey/CardToken/IP asla yok (redaction 01'de kuruldu; burada yalnız projeksiyon).

### Faz 7B — Failure→review contract + fault matrix (Yusuf, `feat/payment-failure-review-and-faults`)

Dosya sınırı: `services/review.py` (payment reason-code'ları), mock_moka `fault_injection.py`, testler.

1. **Failure→review kontratı:** `PAYMENT_POOL_CREATION_FAILED` · `PAYMENT_APPROVE_FAILED` · `PAYMENT_RECONCILE_AMBIGUOUS` · `PAYMENT_UNDO_BLOCKED` reason-code'lu case'ler (phase=payment); resolve akışları (retry tetikleme action'ı dahil).
2. **Mock fault matrix genişletmesi** (Moka §14.4, §22.11): `DEMO-TOKEN-TIMEOUT-AFTER-CREATE` (mock persist eder, cevap gecikir/kesilir) · approve-timeout fault'u · `statement_closed` fixture'ı · decline. Hepsi `MOCK_MOKA_FAULTS_ENABLED=true` iken.
3. **Test matrisi:** aynı idempotency key ikinci instruction üretmez · timeout-after-create → reconcile bind, duplicate create yok · approve timeout → detail approved → instruction confirmed · retry attempt_no artar · undo yalnız yetkili aktörle · reconciliation drift bulur · secret leakage (trace/log/event) taraması.

## Paralellik ve merge sırası

7A ∥ 7B (kesişim yok; review reason-code'ları Yusuf'un servisinde, Berke tüketir). Gate: v2 Program 5 kabulleri + fault matrisinin tamamı mock'a karşı yeşil.

## Repo güvenliği

- Migration additive (018); mevcut akışlara yeni zorunluluk eklenmez — reconcile/retry/undo hepsi ek uçlar.
- Gateway contract değişikliği yalnız `refund` eklemesi; contracts.py freeze kuralı gereği iki taraf onaylı tek PR.
- Legacy yol etkilenmez.

## Kabul kriterleri

v2 Program 5 listesi birebir (idempotency · retry=attempt · provider failure state kaybetmez · confirmation → released · reconciliation drift · refund/reversal audit · background crash recoverable) + Moka §25/10 (unknown sonuçlar reconcile ile çözülür) + trace ucunun redaction testleri.

## Doc-sync

ARCHITECTURE §3.3 (reconciliation/undo/refund + trace), §4.1 (payment-ops uçları), §5 (processing_jobs), §6 (yeni kural: "undo/refund yalnız yetkili insan aksiyonudur"); AGENTS özet + Pratik notlar (fault token'ları, demo reconcile butonu).
