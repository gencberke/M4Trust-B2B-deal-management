# RAG Context Builder ve Güvenlik-Aware Retrieval Katmanı — Done

## Status

done

## Source plan

`plans/done/rag_context_builder_ve_guvenlik_katmani.md` (uygulama sırasında `plans/ready/`'deydi)

## Implementation report

`plans/review/rag_context_builder_ve_guvenlik_katmani_review.md`

## Summary

CLI extraction hattına ContextBuilder orkestrasyon katmanı (çoklu query, çoklu koleksiyon, dedupe/kota/12k limit, kaynak-tipli `formatted_for_llm`), `security_controls` koleksiyon iskeleti + 6 kontrollük PCI DSS kontrol haritası ve kart-verisi guardrail'i (PAN+Luhn maskeleme, CVV/track/PIN → blocking, canlı LLM çağrısının deterministik atlanması) eklendi. `extract()` imzası plana uygun olarak `ContextPack | None`'a geçti; §4.2 şeması donuk kaldı.

## Review result

**Accepted** — küçük takip kalemleriyle.

## Evidence checked

- Files inspected:
  - `plans/done/rag_context_builder_ve_guvenlik_katmani.md` — durum bloğu + 3 sapma işlenmiş, `done/`'a taşınmış ✓
  - `scripts/extract_contract.py:155-161` — blocking + provider==openai → canlı çağrı atlanır, tip-tutarlı `ExtractionResult(status="needs_review", data=None, reason=…)` (plan pini birebir) ✓
  - `services/privacy.py:106,129,158` — kart placeholder'ları (`[[CARD_*]]`) `mapping`'e girmiyor → restore hiçbir koşulda kart verisini geri açamaz (DO_NOT_RESTORE) ✓
  - `ARCHITECTURE.md` §1/§2/§3.1/§3.2/§3.5 — doc-sync yapılmış: yeni modül dizinde, üç koleksiyon stack satırında, yeni imza §3.1'de, ContextBuilder + distance semantiği §3.2'de, PrivacyReport/blocking §3.5'te ✓; `AGENTS.md` pratik notlar güncel ✓
- Tests or verification:
  - `pytest -q` bağımsız yeniden çalıştırıldı: **91 passed** (baseline 58 + 33 yeni) ✓
  - Rapordaki CLI smoke sonuçları (fake uçtan uca + CVV/openai blocking, exit 2) rapor beyanı olarak kabul edildi; blocking kod yolu satır satır doğrulandı.

## Sapma değerlendirmesi

Üç sapma da makul: (1) `--k`'nın ContextBuilder modunda etkisizliği pinlenmiş `build()` imzasını korumak için doğru tercih; (2) security embed'inin ertelenmesi planın açıkça bloker saymadığı durum; (3) `getattr` fallback davranışsal fark yaratmıyor. Kapsam sızması yok — validator'a dokunulmamış (plan gereği).

## Remaining notes

- **security_controls embed bekliyor:** RAG deps kurulu ortamda `pip install -r requirements.txt` + `python scripts/build_rag.py`, ardından koşullu security retrieval'ın gerçek koleksiyonla duman testi.
- **Validator planı yazılmalı:** "maskelenmemiş hassas alan → NEEDS_REVIEW" ve "kart placeholder sızıntısı → REJECT" kontrolleri, hâlâ yazılmamış olan backend iskeleti planının kapsamına devredildi (ikinci kez devir — o plan önceliklendirilirken unutulmamalı).
- Değişiklikler `feature/rag-context-builder` branch'inde, commit kullanıcıya ait (henüz commit'lenmedi).
