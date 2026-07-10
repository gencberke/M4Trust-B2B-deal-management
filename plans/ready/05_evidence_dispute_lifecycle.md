# 05 — First-Class Evidence Records ve İnsan Kontrollü Dispute (Program 3)

> **Durum:** Ready — 2026-07-10 · **Master ref:** v2 §2.12, §5.16-5.17, Program 3, Wave 4
> **Bağımlılık:** 04 tamam (account akışı ratification + `funding_pending`'e kadar çalışıyor; gerçek funding 06'da — harita Revizyon #1). Integration branch: `program/domain-evolution-v2`
> **Branch'ler:** Yusuf `feat/evidence-authorized-ingestion` → `feat/dispute-review-lifecycle` (ikisi de onun domain'i, sıralı) · Berke `feat/evidence-bundle-semantics` + settlement hook commit'leri + **6A'ya erken başlangıç** (harita Revizyon #5 / §7; v2 Wave-4'ün "iş yüküne göre ters" opsiyonu kullanıldı)
> **Tahmin:** 4-5 gün (paralel)

## Amaç

Kanıtı event payload'ı olmaktan çıkarıp first-class kayda dönüştürmek (kim, hangi entity adına, hangi hash'le sundu), dispute'u yalnız yetkili insanın açabildiği bir yaşam döngüsü yapmak ve evidence bundle GET'inin side-effect'ini kaldırmak. **Mevcut karar/tracking semantiği değişmez** — settlement, kanıtları legacy adapter üzerinden aynı `DeliveryEvidence` şekliyle okumaya devam eder.

## Fazlar

### Faz 5A — Authorized evidence ingestion (Yusuf, `feat/evidence-authorized-ingestion`)

Dosya sınırı: `services/evidence_records.py`, `repositories/evidence.py`, `routers/evidence_submit.py`, `db/migrations/013*`. (`routers/delivery.py`'ye DOKUNULMAZ — legacy uçlar H0 halleriyle aynen kalır; sahibi Berke.)

1. **013_evidence_records:** v2 §5.16 (+ `UNIQUE(transaction_id, evidence_type, external_reference)` ve dosya için `UNIQUE(transaction_id, file_sha256)` idempotency kısıtları; `milestone_id` nullable — 06'da dolar).
2. **EvidenceService** — donmuş imzalar (v2 §8.6): `submit_evidence / verify_evidence / collect_transaction_delivery_evidence / collect_milestone_evidence`.
3. **Yeni account uçları** (§14): `POST /evidence/e-irsaliye` · `POST /evidence/video` — session + transaction assignment yetkisi (`require_evidence_submitter`: seller-side assignment veya manager; buyer 403). Payload/file SHA-256 hesaplanır; video dosyası DocumentStorageProvider'a yazılır (`storage_ref`); analyzer provider/version kaydedilir. Business event artık yalnız `evidence_id` + güvenli özet taşır (raw payload event'e kopyalanmaz — v2 §4.7 yönünde; account akışı için).
4. **Legacy adapter (kritik uyum, v2 Faz 3B):** `collect_transaction_delivery_evidence(conn, transaction_id) -> DeliveryEvidence` — account işlemlerde `evidence_records`'tan, legacy işlemlerde bugünkü event-tabanlı yoldan okur. `settlement.py::evaluate_settlement` çağrısının bu fonksiyona geçirilmesi **Berke'nin ayrı entegrasyon commit'idir** (settlement.py onun dosyası; tek satırlık kaynak değişimi, `decide()` imzası aynı). Legacy delivery uçları (H0 token'lı halleriyle) `LEGACY_CAPABILITY_ACCESS_ENABLED` arkasında çalışmaya devam eder.
5. Duplicate policy: aynı `external_reference`/`file_sha256` → idempotent cevap (mevcut kayıt döner), event tekrarlanmaz.
6. **Test notu:** Account işlemler 06'ya kadar `active` olamaz (funding orada başlar). Account evidence API testleri bu fazda state'i fixture ile `active`e set ederek yetki/persistence/idempotency'yi doğrular; funding'li gerçek uçtan uca akış 06 gate'indedir. Legacy delivery uçları default-açık `LEGACY_CAPABILITY_ACCESS_ENABLED` ile çalışmaya devam eder (flag 06'da kapanır).

### Faz 5B — Dispute lifecycle (Yusuf, `feat/dispute-review-lifecycle`)

Dosya sınırı: `services/disputes.py`, `repositories/disputes.py`, `routers/disputes.py`, `db/migrations/014*`.

1. **014_disputes:** `disputes` + `dispute_actions` (v2 §5.17; action'larda `evidence_id` bağlanabilir).
2. **API** (§14): POST open (yalnız buyer/seller **approver** insan aktörü — model/validator/video AÇAMAZ) · GET list · POST actions (comment/attach_evidence/resolve/cancel; actor+entity audit'li).
3. **Hold semantiği:** açık dispute ilgili release'i bloklar — kontrol `settlement.py`'deki tek guard'a eklenir (`has_open_dispute`); dosya Berke'nin olduğu için Yusuf saf `has_open_dispute(conn, transaction_id, milestone_id=None)` fonksiyonunu servis olarak verir, Berke tek commit'le guard'a bağlar (koordinasyon noktası, aynı gün).
4. **Review entegrasyonu (v2 Faz 3C):** video anomalisi (decision `manual_review_required=true`) account işlemde `source_type=video` review case açar (settlement coordinator'dan `ReviewService.open_case`; Berke'nin dosyasına Yusuf'un servisiyle tek çağrı). Case üzerinden ek kanıt istenebilir; `escalate_dispute` action'ı yalnız yetkili insana dispute açtırır — otomatik eskalasyon yok.

### Faz 5C — Evidence bundle semantiği (Berke, `feat/evidence-bundle-semantics`, küçük)

1. `GET /api/transactions/{id}/evidence-bundle`: **saf okuma** — mevcut `build_bundle` çıktısı + evidence_records özeti + (account'ta) package/ratification bilgisi; DB'ye YAZMAZ (v2 §2.12).
2. `POST /api/transactions/{id}/evidence-snapshots`: explicit immutable snapshot (`evidence` tablosuna; package/state/hash ile idempotent; audit event).
3. Eski `GET /evidence` ucu legacy flag arkasında korunur, cevabına deprecation notu eklenir; account UI yeni uçları kullanır.

## Paralellik ve merge sırası

5A → 5B ikisi de Yusuf'ta (kendi domain'i, sıralı). Berke eşzamanlı: 5C + `settlement.py` bağlantı commit'leri (kanıt kaynağı değişimi + dispute/review blocking kontrolleri — 5A/5B merge'lerinden sonra) + **06/6A branch'ine erken başlangıç** (6A'nın migration/persistence işi 05 çıktısına bağımlı değildir). 5C en son. Gate (v2 Wave 4): video anomaly → review hold → insan dispute → evidence bağlı → release yok → dispute resolve → release mümkün.

## Repo güvenliği

- Migration'lar additive; legacy kanıt yolu ve `evidence` tablosu korunur.
- `decide()`/`decision.py` DEĞİŞMEZ; settlement'taki değişiklik yalnız kanıt kaynağı + iki blocking kontrol.
- Video advisory semantiği aynen: miktar üretmez, otomatik dispute yok (regression testleri korunur).

## Kabul kriterleri

v2 Program 3 listesi birebir: anonim/yanlış-participant evidence 403 · evidence actor+entity+hash taşır · duplicate idempotent · GET bundle hiçbir şey yazmaz · snapshot explicit+idempotent · video auto-dispute üretmez · açık dispute release'i bloklar · tracking semantiği korunur · raw token/PII event'e girmez. Full suite + `legacy_compat` seti yeşil.

## Doc-sync

ARCHITECTURE §4.1 (yeni evidence/dispute uçları; eski GET /evidence'ın legacy'e düşmesi), §4.3 (event payload'ı artık evidence_id taşır — account akışı), §5 (evidence_records/disputes tabloları), §6 (6.4'e "kanıt zinciri first-class tablolardan derlenir" güncellemesi); AGENTS özet.
