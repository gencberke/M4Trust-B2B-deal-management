# 06 — Milestone Domain, Funding Units ve Settlement Cutover (Program 4 + Moka M2-M3)

> **Durum:** Ready — 2026-07-10 · **Master ref:** v2 §2.3, §2.7, Program 4 · Moka §3, §9-§13, §17-§19, Wave M2-M3 (v2'nin "Mock Ledger v2" fazı Moka §24 ile SUPERSEDED)
> **Bağımlılık:** 04 (package + funding schedule + FundingCoordinator v1) ve 05 (evidence records) tamam; 01'in gateway/client/mock server'ı hazır. Integration branch: `program/domain-evolution-v2`
> **Branch'ler:** faz bazında aşağıda
> **Tahmin:** 6-8 gün (paralel)

## Amaç

Ratify edilmiş package'ın funding schedule'ını çalıştırılabilir hale getirmek: milestone + funding unit persistence, "**bir funding unit = bir pool payment = tek bütün approve**" (Moka §3.3) modeliyle FundingCoordinator v2, saf milestone evaluator (fixed tranches) ve `settlement.py`'nin account yolunun `PaymentGateway` üzerinden cutover'ı. Kısmi teslim senaryosu artık `capture_ratio`'lu tek ödeme değil, eşiği geçen tranche'ların ayrı ayrı approve edilmesidir (Moka §17.3) — senaryo semantiği (%50 teslim = %50 ödeme) korunur, provider çağrı şekli değişir.

## Fazlar

### Faz 6A — Milestone + funding persistence (Berke, `feat/milestone-funding-persistence`)

Dosya sınırı: `repositories/{milestones,funding_units,provider_payments,release_instructions}.py`, `services/payments/funding_coordinator.py` (v2 iç değişim), `db/migrations/015*`, `016*`, `017*`.

1. **015_milestones:** v2 §5.18 + Moka §17.2 status seti (`funding_unit_approval_pending` dahil; `release_mode = all_or_nothing|fixed_tranches`).
2. **016_funding_units_provider_payments:** Moka §13.1 birebir — `funding_units` (`UNIQUE(provider_profile, other_trx_code)`, `UNIQUE(ratification_package_id, sequence)`, `CHECK(amount_minor > 0)`; status seti Moka §9.2) · `provider_payments` (funding_unit 1:1; `virtual_pos_order_id` unique; internal_status ↔ moka numeric status ayrımı Moka §12) · `provider_operations` (idempotency_key + attempt_no, redacted request, outcome success|failed|unknown).
3. **017_release_instructions:** Moka §13.1; `UNIQUE(funding_unit_id, operation_type)` + `idempotency_key UNIQUE`.
4. Ratification tamamlanınca package'taki schedule persist edilir: milestone satırları + funding unit satırları; `OtherTrxCode = M4T-{tx8}-P{package_version}-U{seq}` (Moka §9.3; retry aynı kodu kullanır, yeni package versiyonu yeni kod üretir).
5. **FundingCoordinator v2** (imza 04'tekiyle aynı): tüm unit'ler için `PaymentGateway.create_pool_payment` — hepsi `pool_created` → `active`; kısmi başarısızlık → `funding_pending` + `PAYMENT_POOL_CREATION_FAILED` review case (Moka §3.7, §10.4); create timeout → `pool_creation_unknown`, kör retry yok, `GetDealerPaymentTrxDetailList(OtherTrxCode)` ile reconcile (Moka §10.6). 04'teki tek-pool v1 davranışı account yolunda bu modelle değiştirilir.
6. `make_payment_gateway(settings)`: `PAYMENT_PROVIDER=fake → FakePaymentGateway` · `moka_http → MokaPaymentDealerClient` (01'de kurulan; **bu fazda ilk kez ana akışa bağlanır**).

### Faz 6B — Saf milestone evaluator (Yusuf, `feat/milestone-evaluator-tranches`)

Dosya sınırı: `services/milestone_decision.py` (yeni saf modül; DB/HTTP/router yok), tabloları süren unit testler.

1. Donmuş tipler (v2 §8.8-8.9, Moka §19): `MilestoneEvidenceSet`, `MilestoneDecision`, `ReleaseCandidate` (= eligible funding unit id'leri; **capture_ratio integration boundary'de YOK**, Moka §19.3).
2. `evaluate_milestone(milestone, evidence_set, review_state)`: trigger/required_evidence eşlemesi · `all_or_nothing`: tüm kanıt tamam → tek unit eligible · `fixed_tranches`: kümülatif doğrulanmış miktar eşiği geçen unit'ler eligible (100 koli / 4×25 örneği; Moka §3.5) · açık review/dispute → hold, hiçbir unit eligible değil · **video semantiği aynen**: miktar üretmez, yüksek güvenli anomali hold+review önerir, otomatik dispute yok.
3. Legacy uyum adaptörü: mevcut `decide()` çıktısındaki oran → "eşik seçimi"ne çevrilen saf yardımcı (Moka §19.3) — yalnız account yolunun geçiş testlerinde kullanılır; `decision.py` DEĞİŞMEZ.
4. Table-driven testler: tranche eşiği tam sınırda / altında / iki eşik birden aşıldığında sıralı eligibility; duplicate evaluation aynı sonuçları verir (idempotent saf fonksiyon).

### Faz 6C — Settlement cutover + ReleaseCoordinator (Berke, `feat/settlement-funding-cutover`; 6A+6B merge SONRASI)

Dosya sınırı: `services/settlement.py`, `services/payments/release_coordinator.py`.

1. `settlement.py` iki yol: **legacy_v1** — bugünkü davranış bit-bit aynı (decide + tek pool MockMokaProvider; dokunulmaz) · **account_v2** — evidence records → milestone evidence set → evaluator → `ReleaseCoordinator`.
2. **ReleaseCoordinator** (v2 §8.9): eligible unit için `ensure_release_instruction` (unique; duplicate evaluation ikinci instruction üretmez) → `submit` → `PaymentGateway.approve_pool_payment(identifier)` (amount YOK) → confirmed'de unit `approved`, milestone aggregate yeniden hesap (`released_amount_minor = Σ approved unit amount`; Moka §17.1), tüm milestone'lar released → transaction `settled`. `PaymentAlreadyApproved` → otomatik failure DEĞİL: detail reconcile, gerçekten approved ise success-equivalent (Moka §11.5). Approve timeout → `approval_unknown` + reconcile.
3. Release guard **tek yerde kalır**: çift ratification + kilitli policy + funded (tüm unit'ler pool_created) + blocking review/dispute yok + unit eligible + instruction idempotent. Router'lar provider çağırmaz.
4. `undo_pool_approval` bu fazda otomasyona BAĞLANMAZ (yalnız 07'deki yetkili reviewer aksiyonu; Moka §11.6).

### Faz 6D — Contract E2E + regression göçü (Yusuf, `feat/moka-multi-release-e2e`)

1. ASGITransport(mock_moka) ile uçtan uca: ratify → 4 unit pool_created → %50 teslim kanıtı → U01+U02 approve (U01 ikinci kez ÇAĞRILMAZ, U03/U04 pending) — Moka §22.10.
2. Kısmi funding başarısızlığı (decline token'lı unit) → funding_pending + review; retry aynı OtherTrxCode ile.
3. Senaryo regression'larının account+funding-unit dünyasına uyarlanması: approval-only = tek unit tam release · document-only tam teslim = tüm unit'ler · **kısmi teslim = fixed-tranche fixture** (Moka §17.3) · video anomaly → ilgili unit approve edilmeden hold · dispute açıkken approve yok.

## Paralellik ve merge sırası

Önce tip freeze (6B'nin tipleri PR'la donar) → 6A ∥ 6B → 6C (yalnız Berke; **milestone evaluator settlement.py içine yazılmaz**) → 6D. Ledger/persistence gelmeden multi-milestone settlement merge edilmez (v2 §2.7 sıra kuralı bu planın iç sırasıdır).

## Repo güvenliği

- `mock_payments` + `MockMokaProvider` + legacy settlement yolu aynen kalır (legacy_v1 işlemler için); kaldırma 09 sonrası removal gate'e tabidir.
- Account yolu `PAYMENT_PROVIDER=fake` ile ağsız çalışır (FakePaymentGateway) — CI'da moka_http'siz tam suite.
- Migration'lar additive; tüm para alanları `amount_minor INTEGER` (float yok).

## Kabul kriterleri

v2 Program 4 listesi (funding-unit diliyle) + Moka §25/10-14: 20/30/40/10 → 4 milestone, toplam exact · ikinci unit release mock'ta çalışır (tek-atışlık kısıt aşıldı) · duplicate evaluation ikinci instruction üretmez · açık dispute/review approve'u bloklar · tüm milestone+instruction'lar tamamlanınca `settled` · %50 teslim demosu İKİ ayrı pool approve ile yürür · evaluator saf ve table-testli · full suite yeşil.

## Doc-sync

ARCHITECTURE §1 (payments/ modülleri), §3.3 (PaymentGateway/funding-unit modeli — "tek pool + capture_ratio" anlatısının değişimi), §4.1 (milestones uçları), §5 (yeni tablolar + milestone/unit state makineleri), §6 (6.1 release guard tanımının funding-unit diliyle güncellenmesi; 6.9 video kuralı aynen); AGENTS özet. YOL_HARITASI senaryo 3'e "fixed-tranche" notu.
