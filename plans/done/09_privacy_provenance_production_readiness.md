# 09 — Privacy, Provenance ve Production Readiness (Program 7)

> **Durum:** Uygulandı — 2026-07-12 · Sapmalar: PostgreSQL geçişi yapılmadı (yalnız readiness envanteri); legacy silinmedi (ayrı planning checklist); rate limit tek-process tasarımında kaldı ve multi-instance için paylaşımlı backend release ön koşuludur.
> **Bağımlılık:** 07 tamamlandı.
> **Uygulama branch'i:** `feat/final-system-audit-hardening`
> **Kapanış raporu:** `plans/audits/final_system_readiness_report.md`

## Amaç

Demo boyunca "kabul edilmiş risk" olarak taşınan boşlukları kapatmak ve production-readiness iddiasının ön koşullarını kurmak. Bu plan feature eklemez; mevcut davranışları sertleştirir. Maddeler bağımsızdır — ekip önceliğe göre kırpabilir (kırpılan madde plana "ertelendi" notuyla işlenir).

## Fazlar

### Faz 9A — Storage, retention, ops (Berke, `feat/hardening-storage-ops`)

1. **Encrypted document storage (migration `020_document_storage_references`):** `LocalDocumentStorageProvider`'a AESGCM şifreleme katmanı (APP_ENCRYPTION_KEY); `transactions.markdown` / ham extraction PII tutarsızlığı için karar uygulanır (v2 §2.14): markdown kolonu document storage'a taşınır (şifreli), tabloda yalnız ref kalır; `extracted_rules`/`extraction_runs` içindeki ham `tax_id` için retention notu + erişim kısıtı belgelenir.
2. **Retention/deletion:** işlem bazlı ham doküman/masked-map temizleme komutu (`scripts/retention_cleanup.py`) + politika dokümanı; runtime DB backup/restore prosedürü (sqlite `.backup` tabanlı script + smoke test).
3. **Structured logging:** request_id + actor + action alanlı JSON log formatter'ı; secret/PII log allowlist testleri.
4. **Tracking policy versioned tablo (04'te ertelenen; migration `019_tracking_policy_versions`):** `tracking_policy_versions` (v2 §5.11) — snapshot'lı package modeli korunarak versiyon tarihçesi eklenir; mevcut `tracking_policies` uyum görünümü olarak kalır.
5. **PostgreSQL readiness notu:** SQLite'a özgü noktaların envanteri (BEGIN IMMEDIATE, busy_timeout, PRAGMA'lar, `INSERT OR IGNORE`) + soyutlama önerisi — yalnız doküman, geçiş bu programda YAPILMAZ (v2 kapsam dışı listesi).

### Faz 9B — Auth akışları + provenance (Yusuf, `feat/hardening-authflows-provenance`)

1. **Rate limiting + login throttling:** basit in-process sayaç (IP+email pencereli) → 429; account lockout eşiği + audit.
2. **Password reset + email verification (migration `021_auth_verification_reset_tokens`):** token'lı akışlar `NotificationProvider` port'u üzerinden (Fake ile demo); `email_verified_at` zorunluluğu env bayraklı. 9B router/middleware MODÜLÜ üretir; `main.py` kaydı Berke'nin integration commit'idir (harita Revizyon #3 genel kuralı).
3. **Provenance genişletmesi (migration `022_extraction_provenance_extensions`)** (v2 §18 hardening): extraction_runs'a OCR engine/version/confidence; RAG collection/chunk id'leri zaten `rag_provenance_json`'da — şema netleştirilir; analyzer model/version evidence_records'ta zorunlu hale gelir.
4. **Dependency/security scan:** CI'a `pip-audit` job'ı; IDOR test taraması matrisinin (v2 §17) tüm resource uçlarına tamamlanması.
5. **Legacy removal ön hazırlığı:** v2 §15.4 removal gate checklist'i çalıştırılır; geçiyorsa ayrı küçük plan (`plans/planning/legacy_capability_removal.md`) yazılır — kolon/uç silme BU planda yapılmaz.

## Repo güvenliği

Her madde bağımsız PR; davranış değişiklikleri (markdown taşıma, email verification zorunluluğu) env bayraklı ve default'ta mevcut davranışı korur; migration'lar additive.

## Kabul kriterleri

Seçilen maddeler için: full suite + yeni sertleştirme testleri yeşil · log/trace/bundle'da secret taraması temiz · backup/restore smoke geçer · rate-limit/lockout/reset akışları testli · kırpılan maddeler plana işlenmiş.

## Doc-sync

ARCHITECTURE §2 (log/scan), §3.5 (storage şifreleme), §5 (tracking_policy_versions), §6 (retention kuralı); AGENTS özet. v2 §2.14'teki "kabul edilmiş risk" kaydı kapatılan maddeler için güncellenir.

## Kapanış kanıtı

- Migration zinciri boş DB ve pre-09 upgrade testleriyle `019-025` dahil doğrulandı; 025, mevcut 023/024 sırasını bozmadan provenance trigger'larını düzeltir.
- Storage round-trip, nonce çeşitliliği, wrong-key/corruption/plaintext fail-closed, atomic yarış, retention replay, encrypted migration ve backup/restore smoke testleri eklendi.
- Auth throttling/lockout/enumeration-safe reset, hashed single-use token replay/expiry, verification, session revocation ve fake/SMTP notification adapter testleri eklendi.
- OCR/LLM/RAG/analyzer provenance compatibility testleri; structured log leak testleri; acting-entity invitation/participant/ratification/transaction/payment/review matrisi genişletildi.
- CI güvenlik workflow'u `pip-audit`, Bandit high severity, npm audit, direct startup ve Gitleaks kapılarını çalıştırır. Operasyon ve PostgreSQL envanteri `docs/` altındadır.
