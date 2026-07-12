# 06X — Plan 06 Kapanış Güvenliği ve Entegrasyon Remediation

> **Durum:** Uygulandı — 2026-07-12 · Sapmalar: (1) Tek milestone'lu eski account fixture'larında evidence service deterministik auto-bind yapar; çoklu adayda fail-closed `EVIDENCE_MILESTONE_REQUIRED` uygulanır. (2) Settlement video resolution mevcut frozen review action `resolve_continue` + allowlist resolution code'larıyla genişletildi; yeni migration gerekmedi. (3) `moka_http` legacy yolu sessiz fallback yerine kontrollü `LEGACY_PAYMENT_PROVIDER_UNSUPPORTED` 409 ile kapatıldı. (4) Provider detail amount/currency boşsa package değerleriyle reconcile edilir, doluysa drift fail-closed reddedilir. (5) Legacy settlement test fixture'ı `legacy_compat` marker'ına taşındı. (6) Legacy tracking-policy mutation uçları da capability kill-switch kapsamına alındı.
> **Kaynak:** `plan_00_06_retrospective_architecture_and_integration_audit.md` raporunun `673a4d0` snapshot'ı, son master kapanış commit'i `3d02a28` ve master `75eeb63` sonrası yeniden denetimi
> **Bağımlılık:** 00–06 uygulama kodu master'da. Bu plan **07'den önce** uygulanır.
> **Kapsam ilkesi:** Yeni ödeme özelliği eklemez; Plan 06'nın runtime güvenlik/tutarlılık açıklarını ve kapanış dokümantasyonu çelişkilerini giderir. `ExtractionJSON`, Moka frozen contract'ları ve legacy tablo kaldırımı kapsam dışıdır.

## 1. Neden 06X gerekiyor?

Retrospektif rapor doğru bir pre-closure fotoğrafı çıkarmıştır; ancak rapordan sonra gelen `3d02a28` ve master merge'i bulguların bir bölümünü kapatmıştır. Güncel kod ve `909 passed` test tabanı üzerinden durum şöyledir:

| Retrospektif bulgu | Son commit sonrası durum | 06X kararı |
|---|---|---|
| B-1 — account settlement runtime'da çağrılmıyor | **Kapandı:** iki account evidence submit ucu `evaluate_settlement` çağırıyor | Regresyon/E2E ile kalıcılaştır |
| B-2 — default-off, doc-sync, master merge ve lifecycle kapanışı yok | **Kısmen kapandı:** default `false`, fixture marker'ı, master merge'i ve ana doc-sync yapıldı; fakat `06` dosyası hâlâ `plans/ready/` altında ve bazı root dokümanları eski anlatıyı taşıyor | Lifecycle + doc-sync'i tamamla |
| B-3 — `review_required` video evaluator'a girmiyor | **Ana para güvenliği deliği kapandı:** advisory reader `verified|review_required` okuyor ve `matched_box` kullanıyor | Review çözüm/re-trigger zincirini tamamla |
| B-4 — approvals legacy kill-switch dışında | **Açık** | Zorunlu düzeltme |
| B-5 — `moka_http` legacy approval'da 500 | **Açık** | Zorunlu fail-closed düzeltme |
| B-6 — create reconciliation'da approved unit provider binding'i eksik | **Açık/dormant ama veri tutarlılığı riski** | Plan 07'ye bırakmadan mevcut 6A seam'ini düzelt |

Son commit ayrıca aşağıdaki yeni entegrasyon açıklarını görünür kılmıştır:

1. **HIGH — Milestone kanıtı transaction geneline broadcast ediliyor.** Plan 05, `evidence_records.milestone_id` için “06'da dolar” der; account evidence router'ları hâlâ `milestone_id=None` yazar. `settlement._verified_evidence_rows()` bu NULL kaydı her milestone'a fallback olarak uygular. Birden fazla teslim milestone'unda tek e-irsaliye miktarı birden çok milestone/unit için eligibility üretebilir. Bu, “kanıt hangi milestone'u ispatlıyor?” bağını kaybettirir.
2. **HIGH — Settlement review/dispute kapandıktan sonra release kendiliğinden ilerlemiyor.** Evidence submit ilk evaluation'ı yapar ve video anomaly blocking settlement review açar. Fakat `review.py` blocking `resolve_continue`'ı yalnız `pre_ratification` fazında kabul eder; settlement video case'i için güvenli verification/resolution kontratı yoktur. Review veya dispute kapandıktan sonra da `evaluate_settlement` çağrılmaz. İşlem yeni kanıt gelmezse `active` durumda takılır.
3. **MEDIUM — Exact video replay settlement tetikleyicisini atlıyor.** Video hash'i mevcutsa router settlement çağrısından önce döner. Replay idempotent persistence sağlasa da rollback/recovery veya sonradan kaldırılan bir block sonrasında güvenli re-evaluation sağlayamaz.
4. **MEDIUM — Dokümanlar kendi içinde çelişkili.** `AGENTS.md` Plan 06'yı `plans/done/` altında gösterirken dosya gerçekte `plans/ready/` altındadır. `ARCHITECTURE.md` üst dizin ağacı migration'ları `001,003-014,023` diye sınırlar; §5 migration paragrafı `015-017` için hâlâ “registry'ye alınmaz” der; ratification endpoint açıklaması ikinci ratification sonrası “provider çağrılmaz” der; §6 numaralandırması 10/11'i tekrarlar. `YOL_HARITASI.md` account kısmi teslimi hâlâ tek `partial_capture` oranı gibi anlatır. Canlı program haritası da 06'yı sıradaki plan gösterir.

## 2. Değişmez kararlar

- LLM ödeme kararı vermez; mevcut validator → ratification → deterministic evaluator → settlement/release coordinator zinciri korunur.
- Provider çağrısı ve release guard yalnız `services/settlement.py` ile payment coordinator'larda kalır. Router yalnız public orchestration servisini tetikleyebilir; gateway/provider çağırmaz.
- Bir funding unit = bir pool payment = tek bütün approve. Account yoluna `capture_ratio` geri gelmez.
- `review_required` video **required evidence tamamlamaz** ve miktar üretmez; yalnız advisory hold + blocking insan incelemesi üretir.
- Dispute otomatik açılmaz. Settlement review çözümü yetkili insan aksiyonu ve güvenli reason code gerektirir.
- Unknown provider sonucu failure sayılmaz; reconcile-first ve aynı `OtherTrxCode` ilkesi korunur.
- Plan 07'nin processing jobs, genel reconcile/retry endpoint'leri, undo/refund ve trace işi bu plana taşınmaz.

## 3. Faz 06X-A — Evidence → milestone bağını fail-closed yap

**Etkilenen alanlar:** `routers/evidence_submit.py`, `services/evidence_records.py`, `repositories/milestones.py`, `services/settlement.py`, evidence API testleri ve gerçek-app E2E.

1. Account e-irsaliye ve video submit contract'ına `milestone_id` ekle:
   - e-irsaliye JSON body'de nullable alan;
   - video multipart form'da nullable alan;
   - verilen ID current complete ratification package'a ve aynı transaction'a ait olmalıdır;
   - milestone'un trigger/required-evidence tipi sunulan kanalı kabul etmiyorsa 409 `EVIDENCE_MILESTONE_MISMATCH`.
2. Geriye uyumlu ama fail-closed çözüm:
   - sunulan evidence tipiyle eşleşen **tek** açık milestone varsa server deterministik auto-bind eder;
   - sıfır eşleşme → 409 `EVIDENCE_MILESTONE_NOT_APPLICABLE`;
   - birden fazla eşleşme ve `milestone_id` yok → 409 `EVIDENCE_MILESTONE_REQUIRED`;
   - istemcinin verdiği ID başka transaction/package'a aitse 404/409; IDOR ayrıntısı sızdırılmaz.
3. Required-evidence/quantity hesabında `milestone_id IS NULL` broadcast fallback'ini kaldır. NULL eski kayıtlar release eligibility üretmez; yalnız transaction-level advisory/audit projection'ında kullanılabilir. Video anomaly transaction-wide blocking review açabilir ama NULL video hiçbir milestone'un sözleşmesel video şartını tamamlamaz.
4. Idempotency scope'unu milestone bağıyla doğrula. Aynı `external_reference` veya file hash farklı milestone'a yeniden bağlanamaz; mevcut kayıt başka milestone'a aitse sessiz idempotent dönüş yerine 409 conflict üretir.
5. Migration beklenmez: `evidence_records.milestone_id` zaten vardır. Constraint ihtiyacı çıkarsa eski `013` değiştirilmez; yeni additive migration `024_*` kullanılır.

**Zorunlu testler:**

- İki e-irsaliye milestone'u + tek milestone'a bağlı tam teslim → yalnız bağlı milestone/unit release edilir.
- Ambiguous NULL milestone submit → hiçbir provider çağrısı olmadan 409.
- Başka transaction/package milestone ID'si → fail-closed.
- Transaction-level `review_required` video release'i durdurur ama required-video şartını tamamlamaz.
- Aynı external reference/hash farklı milestone'a taşınamaz.

## 4. Faz 06X-B — Settlement review çözümü ve deterministik re-trigger

**Etkilenen alanlar:** `services/review.py`, `routers/reviews.py`, `routers/disputes.py`, `routers/evidence_submit.py`, `services/settlement.py` veya yeni küçük `services/settlement_trigger.py`, ilgili API/E2E testleri.

1. Tek bir public orchestration fonksiyonu tanımla (`reevaluate_account_settlement` benzeri):
   - yalnız `account_v2 ∧ state=active` iken çalışır;
   - `evaluate_settlement`'ın tek release guard'ını çağırır;
   - router'lara gateway/provider bilgisi sızdırmaz;
   - duplicate çağrı ReleaseCoordinator idempotency kapılarından geçer.
2. Bu tetikleyiciyi şu başarılı mutation'lardan sonra çağır:
   - yeni **ve idempotent replay** e-irsaliye/video submit;
   - dispute `resolve` veya `cancel` ile kapandığında;
   - settlement/payment blocking review güvenli biçimde çözüldüğünde.
3. Settlement video review için açık bir insan çözüm kontratı ekle; pre-ratification `resolve_continue` kurallarını gevşetip bypass üretme:
   - yalnız platform reviewer/admin çözebilir;
   - `resolution_code` allowlist'li ve serbest metinsizdir;
   - `VIDEO_FALSE_POSITIVE` ancak source evidence atomik olarak `rejected` yapıldıktan sonra case'i çözer;
   - `SUPERSEDED_BY_CLEAN_EVIDENCE` ancak aynı milestone'a bağlı daha yeni, verified ve anomaly'siz kanıt varsa case'i çözer;
   - doğrulanmış anomaly “review kapandı” denilerek release edilemez; dispute/ek kanıt akışı gerekir;
   - evidence verification mutation'ı, review action ve audit aynı DB transaction'ında olmalıdır.
4. Mevcut `verify_evidence()` servis seam'ini runtime akışına bu kontrollü review action üzerinden bağla. Genel-purpose, her aktöre açık bir “verified yap” endpoint'i ekleme.
5. Re-evaluation başarısız/unknown provider sonucunda evidence veya insan action kaydını kaybetme davranışını test et. Plan 07 job altyapısı gelene kadar unknown state kalıcı ve reconcile edilebilir olmalıdır; kör provider retry yapılmaz.

**Zorunlu testler:**

- Hasarlı video + tam e-irsaliye → blocking settlement review, sıfır approve.
- Case kapatılmadan tekrar submit/replay → sıfır ek instruction/provider approve.
- `VIDEO_FALSE_POSITIVE` → evidence rejected + case resolved + otomatik re-evaluation; uygun unit yalnız bir kez approve.
- Temiz yeni kanıt olmadan `SUPERSEDED_BY_CLEAN_EVIDENCE` → 409.
- Açık dispute release'i bloklar; resolve/cancel sonrası yeni evidence zorunlu olmadan re-evaluation ilerler.
- Exact video replay settlement'ı güvenle yeniden değerlendirir; analyzer/storage/evidence satırı tekrarlanmaz.

## 5. Faz 06X-C — Legacy kill-switch ve provider profil uyumu

**Etkilenen alanlar:** `routers/approvals.py`, mümkünse ortak legacy guard helper'ı, `config.py` validation/factory sınırı, legacy testleri.

1. `POST /api/transactions/{id}/approvals`, party/manager/delivery/evidence uçlarıyla aynı `LEGACY_CAPABILITY_ACCESS_ENABLED` guard'ını **token çözümünden önce** uygular. Flag `false` iken 403 ve sabit güvenli hata döner; token'ın geçerli/geçersiz olduğuna dair oracle üretmez.
2. Default `false` korunur. Yalnız `legacy_compat` marker'lı dar test seti env ile açar; marker'sız testlerin yanlışlıkla legacy yüzeye bağımlı kalmadığını denetleyen test eklenir.
3. `LEGACY_CAPABILITY_ACCESS_ENABLED=true` ile `PAYMENT_PROVIDER=moka_http|fake` kombinasyonu legacy approval'da 500 üretmez:
   - desteklenen legacy provider yalnız `mock` olarak açıkça tanımlanır;
   - uyumsuz profil startup/config validation'da veya approval funding öncesinde fail-closed, standart 409/503 `LEGACY_PAYMENT_PROVIDER_UNSUPPORTED` döner;
   - `moka_http → mock` şeklinde sessiz fallback **yapılmaz**.

**Zorunlu testler:** flag-off valid/invalid token aynı güvenli sonuç · flag-on legacy mock akışı aynı davranış · flag-on+moka_http provider çağrısı olmadan kontrollü hata · account ratification/funding etkilenmez.

## 6. Faz 06X-D — Create reconciliation veri bütünlüğü

**Etkilenen alanlar:** `services/payments/funding_coordinator.py`, `repositories/provider_payments.py`, 6A persistence ve Moka timeout testleri.

1. `_reconcile_unknown_unit` detail sonucunu `APPROVED` bulduğunda, status'u doğrudan `approved` yapmadan önce `provider_payments` binding'ini `POOL` dalıyla aynı invariant'larla upsert eder (`virtual_pos_order_id`, OtherTrxCode, amount, currency, provider profile, uygun internal status).
2. Detail'deki kimlik/tutar/para birimi stored funding unit ile uyuşmuyorsa fail-closed drift sonucu üret; unit'i approved sayma ve release'e geçirme. Mevcut güvenli review reason-code'u kullan veya 07 kontratına scope creep etmeden dar bir payment blocking case aç.
3. Provider payment binding + unit status + operation kaydı aynı DB transaction'ında kalır. Kör create/approve retry yoktur.
4. Bu düzeltme Plan 07'nin genel reconciliation servisini supersede etmez; yalnız 06'nın hâlihazırda runtime'da kullandığı create-time reconcile seam'ini tutarlı yapar.

**Zorunlu testler:** timeout-after-create ardından detail=POOL bind · detail=APPROVED bind + 1:1 provider row · replay ikinci provider row üretmez · drift approved sayılmaz · provider row olmadan `approved` unit kalmadığını doğrulayan invariant testi.

## 7. Faz 06X-E — Gerçek-app kapanış gate'i ve doc-sync

1. İzole router/service testlerine ek olarak `create_app()` + gerçek startup migration + session/CSRF/assignment kullanan account E2E ekle:
   - package build → çift ratification → funding → milestone-bound %50 evidence → iki ayrı unit approve → replay no-op → kalan evidence → settled;
   - anomaly → review → güvenli resolution → re-evaluation;
   - dispute → block → resolve → re-evaluation.
2. `plans/done/06_milestone_funding_units_settlement.md` dosyasının uygulandı durum bloğu korunur; 06X kapanışında 06 ve 06X `done/` altında birlikte tutulur ve sapmalar/test sayısı yazılır.
3. Root doc-sync:
   - `ARCHITECTURE.md` §1 migration/modül ağacına 015-017'yi ekle ve provider'sız eski FundingCoordinator açıklamasını güncelle;
   - §4.1 ratification satırını gerçek funding çağrısıyla, evidence satırlarını milestone binding + settlement trigger/replay semantiğiyle güncelle;
   - §5 migration sırasına 015-017'yi gerçekten ekle, “registry'ye alınmaz” cümlesini kaldır, milestone evidence scope'unu yaz;
   - §6 invariant numaralarını tekil/sıralı yap ve review-resolution/re-trigger kuralını ekle;
   - `AGENTS.md` Plan 06 linkini gerçek `plans/done/` yolu ile doğrula, 06X kapanış özetini ve güncel test sayısını ekle;
   - `YOL_HARITASI.md` kısmi teslim senaryosunda account=fixed-tranche funding units, legacy=`partial_capture` ayrımını yaz;
   - `plans/planning/program_haritasi_paralel_calisma.md` Plan 06 kapanışı + 06X remediation notunu ekle, sıradaki uygulanabilir planı 07 olarak göster.
4. Extraction şeması değişmediği için §4.2'ye yalnız “değişmedi” notu yeterlidir; şema snapshot testi aynen yeşil kalır.

## 8. Kabul kriterleri

- Tek evidence kaydı birden çok milestone'a release eligibility veremez.
- Her account evidence submit/replay authorized product path üzerinden settlement'ı güvenle tetikler.
- Settlement review ve dispute kapanışı yeni kanıt hilesi gerektirmeden, idempotent re-evaluation üretir.
- Video anomaly, insan tarafından güvenli resolution koşulu karşılanmadan release edilemez; video miktar üretmez ve otomatik dispute açmaz.
- Legacy approval dahil bütün capability yüzeyi default-off kill-switch arkasındadır.
- Legacy+moka_http konfigürasyonu 500 veya sessiz mock fallback üretmez.
- Reconciled approved funding unit her zaman 1:1 `provider_payments` binding'ine sahiptir; drift fail-closed'dur.
- Plan 06 ve 06X lifecycle/doc-sync tutarlıdır; root dokümanlarda 015-017 veya “provider çağrılmaz” eski anlatısı kalmaz.
- `ExtractionJSON` yapısal snapshot'ı değişmez; frozen Moka contract dosyaları değişmez.
- Full suite ve CI yeşildir; kapanış raporunda test sayısı, warning/skip bilgisi ve sapmalar yazılır.

## 9. Kapsam dışı / Plan 07 sınırı

- `018_processing_jobs`, startup recovery queue, genel reconcile/retry endpoint'leri
- undo approval, refund, bilateral reversal
- payment trace endpoint'i ve geniş fault matrix
- frontend account slice'ları
- legacy tablo/token kolonlarını kaldırma veya hash migration'ı
- session cookie production hardening, NER masking ve provenance 019-022 işleri

Bu maddeler 07/08/09 planlarında kalır. 06X sırasında bir düzeltme bunlardan birini zorunlu kılarsa uygulama durdurulur ve plan sınırı yeniden değerlendirilir.

## 11. Uygulama doğrulaması

- Hedefli evidence/settlement/review/dispute/provider testleri yeşil.
- Tam suite: **913 passed, 45 warnings** (localhost mock Moka E2E dahil; sandbox port kısıtı nedeniyle escalated test çalıştırması kullanıldı). Kapanış sonrası blocker düzeltmesi olarak e-irsaliye router'ının request `milestone_id` alanını servise aktarması ve iki gerçek HTTP regresyon senaryosu eklendi.
- `ExtractionJSON` ve frozen Moka contract'ları değiştirilmedi; yeni migration eklenmedi.
- Plan 06 ve 06X `plans/done/` altına taşındı; ARCHITECTURE, AGENTS, YOL_HARITASI ve program haritası doc-sync edildi.

## 10. Önerilen uygulama sırası

`06X-A (milestone binding)` → `06X-B (review/re-trigger)` → `06X-C ∥ 06X-D` → `06X-E (real-app gate + doc-sync + plan move)`.

Para güvenliği nedeniyle A ve B tamamlanmadan yalnız legacy/doc-sync düzeltmeleriyle plan kapatılmaz. 07'ye başlama koşulu, bu planın `done/` altında olması ve gerçek-app gate'inin yeşil geçmesidir.
