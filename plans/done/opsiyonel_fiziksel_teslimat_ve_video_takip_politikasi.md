# Opsiyonel Fiziksel Teslimat ve Video Takip Politikası

> **Durum:** Uygulandı (backend) — 2026-07-10 · Doğrulama: `cd code && ./.venv/bin/python -m pytest -q` → **211 passed, 0 failed** (baseline: 180 passed). Kod incelemesi sonrası sözleşmesel-video açığı kapatıldı (bkz. sapma 2).
>
> **Sapmalar:**
> 1. **Faz 6 (frontend) uygulanmadı** — bu iş bilinçli olarak yalnızca backend'i kapsar; `code/frontend/` hâlâ boştur ve UI ayrı bir planda ele alınacaktır. Dolayısıyla "Frontend build başarılıdır" kabul kriteri bu turda uygulanmaz.
> 2. **Sözleşmesel video `tracking_mode=document_and_video` zorunlu kılar.** Plan §7 yalnızca "yönetici video zorunluluğunu kaldıramaz" diyordu. `off` modunda e-irsaliye kanalı da kapalı olacağından işlem karara bağlanamazdı; `document_only` modunda ise video `advisory_evidence`e girmediği için yalnızca varlığı sayılır, hasar ve sayım ayrışması hiç değerlendirilmezdi (kod incelemesinde yakalandı). Her ikisi de `CONTRACTUAL_VIDEO_REQUIRES_VIDEO_TRACKING` ile reddedilir; ayrıca `decide()` video sinyalini advisory **ve** sözleşmesel kanıt için aynı biçimde okur (saf katman upstream doğrulamaya bel bağlamaz).
> 3. **Kanıt kanalı guard sırası:** "kanal etkin mi?" kontrolü `decided` kontrolünden **önce** gelir; böylece takip edilmeyen kanal işlemin durumundan bağımsız olarak `TRACKING_NOT_ENABLED` döner. Karar verilmiş işleme geç gelen video yine de **analizden önce** `TRANSACTION_DECIDED` ile reddedilir.
> 4. **Şema snapshot'ı** JSON Schema literal'i yerine yapısal snapshot olarak yazıldı (alan adları + enum üyeleri, `tests/test_extraction_schema.py`) — pydantic sürüm oynamalarına karşı kırılgan olmasın diye. `ExtractionJSON` dosyası bu işte hiç değişmedi (`git diff` boş).
> 5. **`source_quote` public cevaplarda korunur, maskelenir.** İlk uygulamada tümden düşürülmüştü; bu, "AI önerir, taraflar dayanağı görüp onaylar" zincirini zayıflattığı için kod incelemesinde geri alındı. Artık `privacy.analyze()`den geçirilip döndürülüyor (ham alıntı yalnız DB'de).
> 6. `services/video.py` (paket tarafından gölgelenen ölü modül) bu iş kapsamında silinmedi; ayrı temizlik kalemi olarak duruyor.
>
> **Tür:** Mimari düzeltme + backend uygulama planı  
> **Bağlayıcı referans:** `ARCHITECTURE.md` (§1 · §3.4 · §4.1 · §4.3 · §5 · §6.9-6.11 doc-sync'lendi)

## Status

done

## Goal

M4Trust içinde fiziksel teslimat ve video analizini varsayılan ödeme mekanizması olmaktan çıkarıp, yalnızca uygun işlemlerde yönetici tarafından etkinleştirilen ayrı bir **takip politikası** hâline getirmek.

Hedef davranış:

1. Sistem sözleşmeden fiziksel mal teslimatı ihtimalini yalnızca **öneri** olarak belirler.
2. İşlemi oluşturan yetkili/yönetici, fiziksel teslimatı doğrular ve takip modunu seçer.
3. Takip politikası tarafların onayından önce kilitlenir ve iki tarafa da açıkça gösterilir.
4. E-irsaliye, yalnızca sözleşmesel olarak zorunluysa veya yönetici belge takibini etkinleştirdiyse karar girdisi olur.
5. Video, varsayılan olarak **ikincil ve tavsiye niteliğinde** bir risk sinyalidir.
6. Opsiyonel video eksikliği ödemeyi otomatik olarak bekletmez.
7. Video tek başına teslim edilen miktarı, kısmi ödeme oranını, para bırakmayı veya dispute kararını belirleyemez.
8. Yüksek güvenli video anomalisi doğrudan dispute açmak yerine `hold / manual review` üretir.
9. Fiziksel teslimat takibi kapalı ve sözleşmede harici kanıt gerekmiyorsa işlem video/e-irsaliye beklemeden approval tabanlı deterministik akışta ilerleyebilir.
10. Notebook ile backend arasında kullanılan `ExtractionJSON` şeması değişmeden kalır.

## Background

Mevcut backend akışı aşağıdaki varsayımları taşıyor:

- `delivery_video`, extraction şemasında ödeme tetikleyicisi olabilir.
- `video`, `required_evidence` birleşimine girdiğinde karar motoru videoyu zorunlu kanıt sayar.
- E-irsaliye ve video kanıtları işlem fonlandıktan sonra karar motorunu otomatik tetikler.
- Video sayımı, e-irsaliye yoksa teslim edilen miktar olarak kullanılabilir.
- Video/e-irsaliye ayrışması veya hasar sinyali doğrudan `dispute` oluşturabilir.
- Fake extraction fixture’ı videoyu varsayılan teslimat kanıtı hâline getirir.
- Teslimat endpoint’leri ve video kontrolleri ürünün ana kullanım yolu gibi görünür.

Bu davranış, ürünün daha geniş B2B anlaşma yönetimi iddiasını daraltıyor. Hizmet, danışmanlık, lisans, proje teslimi veya yalnızca taraf onayıyla ilerleyen anlaşmalar ikinci planda kalıyor. Fiziksel mal teslimatı olan işlemlerde dahi video, yöneticinin seçtiği yardımcı bir takip özelliği yerine ödeme kararının merkezi girdisine dönüşüyor.

## Problem statement

Sistem şu iki kavramı birbirine karıştırıyor:

1. **Sözleşmesel yükümlülükler:** Sözleşmede gerçekten yazan ödeme tetikleri ve gerekli kanıtlar.
2. **Platformun operasyonel takip tercihi:** Yöneticinin risk azaltmak için açtığı e-irsaliye/video takibi.

Bu ayrım yapılmadığında:

- Platform tercihi, sözleşme şartıymış gibi ödeme akışını bloke edebilir.
- Video modelinin eksik veya hatalı sayımı doğrudan para hareketine etki edebilir.
- Fiziksel teslimat içermeyen anlaşmalar için doğal bir akış kalmaz.
- Video yüklenmemesi gereksiz `hold` üretir.
- Video anomalisi insan değerlendirmesi olmadan dispute’a dönüşür.
- UI, videoyu yardımcı bir risk metriği yerine ürünün ana özelliği gibi sunar.
- Notebook ve extraction benchmark’ı, aslında operasyonel bir platform tercihini modelin sözleşmeden çıkarması gereken zorunlu alanmış gibi temsil edebilir.

## Locked design decisions

Aşağıdaki kararlar bu plan için bağlayıcıdır.

### 1. Extraction şeması korunur

`code/backend/app/schemas/extraction.py` içindeki `ExtractionJSON` bu plan kapsamında alan ekleme/çıkarma/yeniden adlandırma olmadan korunacaktır.

Özellikle:

- `Trigger.delivery_video` kaldırılmayacaktır.
- `RequiredEvidence.video` kaldırılmayacaktır.
- Notebook benchmark contract’ı değiştirilmeyecektir.
- Bu alanlar yalnızca sözleşmede video açıkça bir ödeme/kanıt şartıysa kullanılacaktır.
- Platformun opsiyonel video takibi extraction JSON içine yazılmayacaktır.

### 2. Takip tercihi ayrı bir domain modeli olacaktır

Yönetici tercihi, transaction’a bağlı ayrı bir `TrackingPolicy` olarak tutulacaktır.

Extraction:

- sözleşmenin ne söylediğini,

TrackingPolicy:

- platformda neyin takip edileceğini

temsil edecektir.

### 3. Video varsayılan olarak advisory’dir

Platform tarafından açılan video takibinin rolü:

```text
video_role = advisory
```

olacaktır.

Opsiyonel video:

- `required_evidence` birleşimine eklenmez,
- yokluğu tek başına `hold` üretmez,
- tek başına `capture` veya `partial_capture` üretmez,
- tek başına dispute açmaz,
- e-irsaliye miktarının yerine geçmez,
- yalnızca yeterli güven seviyesinde destekleyici veya şüphe artırıcı sinyal üretir.

### 4. E-irsaliye birincil fiziksel teslimat metriğidir

Yönetici fiziksel teslimat takibini etkinleştirdiyse:

- `document_only` ve `document_and_video` modlarında e-irsaliye birincil nicel kanıttır.
- Kısmi teslim oranı yalnızca e-irsaliye veya sözleşmesel olarak kabul edilmiş başka bir birincil kanıttan hesaplanır.
- Video sayımı kısmi ödeme oranının kaynağı olamaz.

### 5. Video anomalisi otomatik dispute değildir

Opsiyonel videoda:

- yüksek güvenli sayım ayrışması,
- yüksek güvenli ve ilgili koliyle eşleşen hasar sinyali

doğrudan `dispute` yerine:

```text
hold + manual_review_required
```

üretir.

Dispute, daha sonra yetkili insan kararıyla açılabilecek ticari bir aksiyondur. Bu plan kapsamında video modeline dispute yetkisi verilmez.

### 6. Politika taraf onayından önce görünür ve kilitlidir

- Yönetici politikayı oluşturur.
- Politika açıkça kilitlenmeden buyer/seller onayı kabul edilmez.
- Kilitlenen politika party view’da iki tarafa da gösterilir.
- Kilit sonrası politika değiştirilemez.
- Hackathon kapsamında amendment/re-approval akışı kurulmaz; yanlış politika için yeni transaction açılması kabul edilebilir.
- Token, event veya log içinde açık biçimde tutulmaz.

### 7. Sözleşmesel kanıt her zaman önceliklidir

Sözleşmede video veya e-irsaliye açıkça zorunluysa yönetici bunu sessizce devre dışı bırakamaz.

Örnek:

- Sözleşme `required_evidence=["video"]` diyorsa `tracking_mode=off` seçimi video zorunluluğunu kaldırmaz.
- Yönetici arayüzü bunu “Sözleşmesel zorunluluk” olarak gösterir.
- Politika kilitlenmeden önce çelişki çözülmelidir.
- Sözleşme kuralı değiştirilecekse tarafların göreceği rule sheet de değişeceğinden ayrı bir rule-edit/re-approval akışı gerekir; bu planın kapsamı dışındadır.

## Terminology

### Contractual evidence

Extraction JSON içindeki `payment_rules[].required_evidence` alanından gelen ve sözleşmede açık dayanağı bulunan kanıtlar.

### Operational tracking

Yöneticinin platform özelliği olarak etkinleştirdiği takip.

### Physical delivery recommendation

Sistemin extraction çıktısından ürettiği, bağlayıcı olmayan:

```text
yes | no | uncertain
```

önerisi.

### Tracking mode

```text
off
document_only
document_and_video
```

### Effective evidence requirements

Karar motorunun gerçekten beklediği kanıt kümesi:

```text
contractual requirements
+ manager-enabled primary tracking requirements
```

Opsiyonel advisory video bu kümeye eklenmez.

## Target behavior matrix

| Durum | E-irsaliye | Video | Karar üzerindeki etki |
|---|---|---|---|
| `tracking_mode=off`, sözleşmede teslimat kanıtı yok | Beklenmez | Devre dışı | Approval tabanlı kurallar tamamlandıysa harici teslimat kanıtı beklenmez |
| `tracking_mode=off`, sözleşmede e-irsaliye zorunlu | Zorunlu | Devre dışı veya sözleşmeye göre | Sözleşmesel gereksinim uygulanır |
| `tracking_mode=off`, sözleşmede video zorunlu | Sözleşmeye göre | Zorunlu | Yönetici tercihi sözleşmeyi geçersiz kılamaz |
| `document_only` | Birincil takip metriği | Devre dışı | Eksikse hold; miktar/capture ratio e-irsaliyeden |
| `document_and_video`, video yok | Birincil takip metriği | Opsiyonel, yok | Video yokluğu tek başına hold değildir |
| `document_and_video`, video uyumlu | Birincil | Destekleyici | Karara güven sinyali ekler; miktarı değiştirmez |
| `document_and_video`, video düşük confidence | Birincil | Bilgilendirici | Warning; otomatik hold/dispute yok |
| `document_and_video`, yüksek güvenli ayrışma | Birincil | Şüphe sinyali | Hold + manual review; release yok |
| `document_and_video`, ilgili hasar sinyali | Birincil | Şüphe sinyali | Hold + manual review; release yok |
| Yalnızca video yüklenmiş | Yok | Var | Capture/partial yok; video teslimat miktarı sayılmaz |
| Fiziksel teslimat doğrulanmamış | Takip açılamaz | Takip açılamaz | Yönetici önce fiziksel teslimatı doğrular |

## Non-goals

Bu plan aşağıdakileri yapmayacaktır:

- Gerçek Moka API entegrasyonu.
- Gerçek e-irsaliye servis entegrasyonu.
- Tam kullanıcı/RBAC sistemi.
- Organizasyon, rol ve kullanıcı tabloları.
- Genel amaçlı çok aşamalı milestone ödeme motorunun tamamen yeniden yazılması.
- Sözleşme kuralı düzenleme ve yeniden taraf onayı akışı.
- Kilitlenmiş tracking policy amendment akışı.
- Otomatik dispute çözümü.
- Video modelini yeniden eğitmek veya farklı model seçmek.
- Roboflow adapter’ının temel inference contract’ını gereksiz yere değiştirmek.
- `ExtractionJSON` veya notebook benchmark şemasını değiştirmek.
- RAG ve LLM extraction prompt’unu fiziksel takip politikasını seçer hâle getirmek.
- E-faturayı veya e-irsaliyeyi gerçek mevzuat servisinden doğrulamak.
- Video gelmesi için zamanlayıcı, queue veya grace-period sistemi kurmak.
- SQLite’tan başka bir veri tabanına geçmek.

## Proposed architecture

### 1. TrackingPolicy domain modeli

Yeni model için önerilen alanlar:

```text
transaction_id
system_physical_delivery_recommendation: yes | no | uncertain
system_recommendation_reasons: list/string JSON
manager_physical_delivery_confirmed: boolean | null
tracking_mode: off | document_only | document_and_video
video_role: advisory
status: draft | locked
configured_at
locked_at
```

İsteğe bağlı fakat yararlı alan:

```text
configured_by: manager
```

`manager_physical_delivery_confirmed` ilk durumda `null` olabilir. Yönetici policy’yi kilitlemeden önce açıkça `true` veya `false` seçmelidir.

### 2. Ayrı persistence

Yeni tablo önerisi:

```text
tracking_policies
```

Her transaction için en fazla bir güncel policy bulunacaktır.

Temel kurallar:

- `transaction_id` unique/primary reference.
- Yeni transaction için policy `draft + off` olarak oluşturulur.
- Extraction tamamlanınca sistem önerisi policy’ye yazılır.
- Yönetici seçimi sistem önerisini değiştirebilir.
- Sistem önerisi ile yönetici kararı ayrı alanlarda kalır; audit izi kaybolmaz.
- Policy kilitlendikten sonra update endpoint’i 409 döner.
- Evidence bundle policy snapshot’ını içerir.

### 3. Manager capability token

Mevcut capability URL yaklaşımı korunarak transaction’a üçüncü token eklenir:

```text
manager_token
buyer_token
seller_token
```

Transaction create cevabı:

```text
id
manager_link
buyer_link
seller_link
```

Manager token yalnızca:

- manager view,
- tracking policy update,
- tracking policy lock

işlemlerinde kullanılacaktır.

Bu plan tam auth sistemi kurmayacaktır.

### 4. Fiziksel teslimat önerisi

Bağlayıcı olmayan öneri, extraction tamamlandıktan sonra deterministik bir helper/service tarafından üretilmelidir.

Örnek sinyaller:

- `commercial_terms.goods` içinde pozitif miktarlı fiziksel birimlerin bulunması,
- birimlerin `adet`, `koli`, `palet`, `kg`, `ton`, `litre`, `metre` gibi fiziksel sinyal vermesi,
- payment rule içinde `e_irsaliye` veya `video` kanıtı bulunması,
- milestone/source quote içinde teslim, sevkiyat, depo, irsaliye, koli, palet gibi sözcüklerin bulunması,
- yalnızca hizmet/lisans/danışmanlık sinyali varsa `no`,
- sinyaller çelişiyorsa `uncertain`.

Kuralların amacı doğru hukuki sınıflandırma yapmak değildir. Amaç, yöneticinin önüne makul bir öneri getirmektir.

Önemli:

- LLM sonucu policy’yi otomatik etkinleştirmez.
- E-irsaliye daha sonra geldiğinde kilitli policy sessizce değişmez.
- Sonradan gelen belge, policy ile çelişiyorsa warning/manual review üretir.
- Sistem false positive ürettiğinde yönetici `physical_delivery=false` seçebilmelidir.

### 5. Effective evidence requirement resolver

Karar motoruna dağınık koşullar eklemek yerine tek bir saf helper/service oluşturulmalıdır.

Sorumluluğu:

```text
resolve_effective_requirements(extraction, tracking_policy)
```

Kavramsal çıktı:

```text
contractual_required_evidence
operational_required_evidence
advisory_evidence
effective_required_evidence
conflicts
```

Kurallar:

- Contractual gereksinimler extraction’dan aynen alınır.
- `document_only` ve `document_and_video`, operasyonel gereksinimlere `e_irsaliye` ekler.
- Opsiyonel platform videosu yalnızca `advisory_evidence` içine girer.
- Sözleşmesel video zorunluluğu varsa video `effective_required_evidence` içinde kalır.
- `physical_delivery=false` iken teslimat takip modu seçilemez.
- Contract ile manager seçimi çelişirse policy lock reddedilir.

Bu resolver saf ve kapsamlı unit testli olmalıdır.

### 6. Decision engine ayrımı

`services/decision.py` saf fonksiyon kalacaktır.

Ancak girdisi policy-aware hâle getirilmelidir. Kod şekli implementere bırakılmakla birlikte şu ayrım korunmalıdır:

- Pure decision logic: `decision.py`
- DB/event/payment orchestration: ayrı coordinator/service

Mevcut `_attempt_decision()` mantığının router içinde kalması yerine örneğin:

```text
services/settlement.py
```

veya benzer bir orchestration servisine taşınması önerilir.

Bunun nedenleri:

- Approval tamamlandığında da değerlendirme çalıştırılabilmeli.
- E-irsaliye geldiğinde de aynı değerlendirme kullanılmalı.
- Video geldiğinde de aynı değerlendirme kullanılmalı.
- Release guard tek yerde kalmalı.
- Router’lar birbirinin private fonksiyonlarını import etmemeli.
- Decision engine I/O’suz kalmalı.

### 7. Approval-only işlem desteği

Fiziksel takip kapalı ve effective requirement kümesinde harici kanıt yoksa transaction video/e-irsaliye beklememelidir.

İki taraf onayından ve pool payment oluşturulmasından sonra settlement coordinator bir değerlendirme çalıştırmalıdır.

Minimum davranış:

- Yalnızca contract/approval ile tamamlanan kurallar için harici delivery event’i beklenmez.
- Sözleşmesel veya manager-enabled e-irsaliye/video gereksinimi varsa işlem evidence bekler.
- Bu değişiklik tam milestone engine değildir; yalnızca “kanıt gerekmeyen işlem delivery endpoint’i beklemesin” güvenlik ve kullanılabilirlik düzeltmesidir.
- Mixed milestone davranışında mevcut sistemin sınırları açıkça korunmalı ve dokümante edilmelidir.

### 8. Video karar semantiği

Opsiyonel video için önerilen kurallar:

1. Video yoksa:
   - `document_and_video` policy’si geçersiz sayılmaz.
   - E-irsaliye ve diğer zorunlu kanıtlar yeterliyse karar ilerleyebilir.
   - Sonuçta `VIDEO_NOT_PROVIDED` informational finding bulunabilir; bloklayıcı değildir.

2. Video var, confidence düşükse:
   - Sayım/hasar sinyali karar verdirmez.
   - Warning üretilir.
   - Video yokmuş gibi birincil kanıt üzerinden devam edilir.

3. Video var, confidence yeterli ve e-irsaliye ile uyumluysa:
   - Destekleyici finding üretilir.
   - Capture ratio değişmez.

4. Video var, confidence yeterli ve nicel ayrışma eşik üstündeyse:
   - `hold`.
   - `capture_ratio=0`.
   - `manual_review_required=true`.
   - Otomatik dispute event’i yok.

5. Hasar sinyali varsa:
   - Yalnızca yeterli confidence ve ilgili koli/paketle anlamlı ilişki varsa bloklayıcı hold düşünülür.
   - Düşük confidence veya eşleşmemiş sinyal warning olarak kalır.
   - Raw model çıktısı karar rationale’ına kontrolsüz biçimde basılmaz.

6. Video tek başınaysa:
   - `delivered_quantity = video.unit_count` yapılmaz.
   - `partial_capture` veya `capture` üretilemez.
   - Birincil kanıt beklenir veya sözleşme gereğine göre hold edilir.

### 9. DecisionResult findings

Yalnızca serbest metin rationale’a bağımlı kalmamak için karar sonucuna yapılandırılmış finding’ler eklenmesi önerilir.

Örnek kategoriler:

```text
MISSING_REQUIRED_EVIDENCE
VIDEO_NOT_PROVIDED
VIDEO_LOW_CONFIDENCE
VIDEO_COUNT_ALIGNED
VIDEO_COUNT_DIVERGENCE
VIDEO_DAMAGE_SIGNAL
POLICY_CONTRACT_CONFLICT
PRIMARY_EVIDENCE_MISSING
```

Her finding en az:

```text
code
severity: info | warning | review
message
```

taşımalıdır.

Bu alan UI ve evidence bundle’da kullanılabilir. Existing API uyumluluğu için `action`, `capture_ratio`, `rationale` korunmalıdır.

## API changes

### Transaction create

`POST /api/transactions` cevabına:

```text
manager_link
```

eklenir.

Token response dışında event/log içine yazılmaz.

### Manager view

Yeni endpoint önerisi:

```text
GET /api/transactions/{id}/manager-view?token=...
```

Döndürmesi gerekenler:

- transaction state,
- extraction özeti,
- validator sonucu,
- physical delivery system recommendation,
- recommendation reason’ları,
- tracking policy draft/locked durumu,
- sözleşmesel e-irsaliye/video zorunlulukları,
- manager’ın seçebileceği geçerli modlar,
- mevcut evidence özeti,
- policy conflict’leri.

Ham markdown ve hassas veri dönmemelidir.

### Tracking policy update

Yeni endpoint önerisi:

```text
PUT /api/transactions/{id}/tracking-policy
```

Body kavramsal olarak:

```text
manager_token
physical_delivery_confirmed
tracking_mode
```

Kurallar:

- manager token zorunlu,
- policy `draft` olmalı,
- `physical_delivery=false` ise mode yalnızca `off`,
- `document_and_video` seçimi video rolünü `advisory` yapar,
- contractual conflict varsa 409 + yapılandırılmış gerekçe,
- update event’i üretilir,
- token event payload’ına girmez.

### Tracking policy lock

Yeni endpoint önerisi:

```text
POST /api/transactions/{id}/tracking-policy/lock
```

Kurallar:

- manager token zorunlu,
- physical delivery confirmation null olamaz,
- policy geçerli olmalı,
- contractual conflict olmamalı,
- lock idempotent olabilir,
- lock sonrası update 409,
- lock event’i üretilir.

### Party view

Mevcut party view’a sade bir `tracking_summary` eklenir:

```text
physical_delivery
tracking_mode
e_irsaliye_tracking_enabled
video_tracking_enabled
video_role
contractual_requirements
```

UI metni teknik enum göstermemeli.

Örnek:

```text
Teslimat takibi: Açık
Birincil doğrulama: E-irsaliye
Video analizi: Yardımcı risk sinyali
Video tek başına ödeme kararı vermez.
```

### Approvals

Approval endpoint’i:

- policy locked değilse 409,
- policy özeti party view’da görünmüyorsa onay kabul etmemeli,
- iki onay sonrası pool payment oluşturmalı,
- ardından settlement coordinator’ı bir kez çağırmalı,
- harici kanıt gerekmiyorsa approval-only akışı tamamlayabilmeli,
- evidence gerekiyorsa `active/evidence_pending` durumunda kalmalı.

### Delivery endpoints

#### E-irsaliye endpoint’i

E-irsaliye yalnızca şu durumlarda kabul edilmelidir:

- sözleşmesel olarak gerekliyse,
- veya manager policy `document_only/document_and_video` ise.

Aksi durumda 409:

```text
Bu işlemde e-irsaliye takibi etkin değil.
```

#### Video endpoint’i

Video yalnızca şu durumlarda kabul edilmelidir:

- sözleşmesel video şartı varsa,
- veya manager policy `document_and_video` ise.

Aksi durumda 409:

```text
Bu işlemde video takibi etkin değil.
```

Karar verilmiş transaction’a geç gelen video kabul edilmemeli veya yalnızca audit amaçlı ayrı davranış açıkça tanımlanmalıdır. Hackathon için en güvenli seçenek: `decided` durumda 409.

## Event changes

Yeni event tipleri önerisi:

```text
tracking_policy_recommended
tracking_policy_updated
tracking_policy_locked
```

Mevcut event’ler korunur:

```text
e_irsaliye_received
delivery_video_analyzed
payment_decision_created
mock_payment_executed
dispute_opened
```

Semantik değişiklik:

- Opsiyonel video anomalisi doğrudan `dispute_opened` üretmez.
- Hold kararı release çağrısı yapmaz.
- Gerekirse `payment_decision_created` içinde action=`hold` ve findings saklanabilir.
- Evidence bundle tracking policy snapshot’ını ve policy event’lerini içerir.

Event payload’larında:

- manager/buyer/seller token,
- ham markdown,
- maskeleme haritası,
- kart verisi

bulunmamalıdır.

## State machine strategy

Transaction state machine mümkün olduğunca korunmalıdır. Tracking policy için ayrı `draft|locked` durumu kullanılacaktır.

Önerilen yaklaşım:

```text
uploaded → extracting → awaiting_review | awaiting_approval | rejected
                         + policy.status=draft
policy locked
→ party approvals açılır
iki approval
→ pool payment + active
effective evidence yok
→ settlement değerlendirmesi
effective evidence var
→ evidence_pending
evidence yeterli ve temiz
→ decided
video anomaly/manual review
→ evidence_pending veya ayrı held görünümü
```

Yeni transaction state eklemek zorunlu değildir. UI:

```text
tracking policy waiting
```

durumunu transaction state’ten değil policy status’ünden türetebilir.

`hold` sonucunda transaction’ın doğrudan `decided` yapılması önerilmez. İnceleme veya ek kanıt bekleniyorsa `evidence_pending`/held durumda kalmalıdır.

## Database and migration plan

### Schema changes

- `transactions` tablosuna `manager_token`.
- Yeni `tracking_policies` tablosu.
- Gerekirse decision findings mevcut event payload’ında saklanır; yeni tablo zorunlu değildir.

### Migration constraints

Repo stdlib SQLite ve `init_db()` kullanıyor. Bu nedenle:

- Yeni tablo `CREATE TABLE IF NOT EXISTS` ile eklenir.
- `manager_token` kolonu için `PRAGMA table_info(transactions)` ile idempotent kontrol yapılır.
- Kolon yoksa additive `ALTER TABLE` uygulanır.
- Yeni transaction’larda manager token transaction oluşturulurken üretilir.
- Eski runtime kayıtları için ya güvenli lazy backfill ya da açıkça belgelenmiş demo DB reset stratejisi seçilir.
- Test DB’leri her zaman yeni şemayla kurulmalıdır.
- Runtime DB reset gerekiyorsa kullanıcı verisini sessizce silen kod yazılmamalıdır; yalnızca geliştirme notu verilmelidir.
- Token’lar loglanmamalı ve evidence’a girmemelidir.

## Backend implementation phases

## Phase 0 — Baseline and design guard

Amaç: Değişiklikten önce gerçek durumu kaydetmek.

Yapılacaklar:

1. `AGENTS.md`, `ARCHITECTURE.md`, bu plan ve ilgili mevcut testleri oku.
2. Mevcut test suite’ini çalıştır ve gerçek baseline sayısını kaydet.
3. Aşağıdaki davranışları mevcut testlerden doğrula:
   - fake fixture videoyu zorunlu kılıyor mu,
   - video yokluğu hold üretiyor mu,
   - video sayımı partial capture kaynağı mı,
   - video anomaly doğrudan dispute açıyor mu,
   - approval sonrası delivery event’i olmadan işlem bekliyor mu.
4. Değiştirilecek public API response’larını ve frontend tüketim noktalarını belirle.
5. Uygulamayı ayrı branch’te yap.
6. `ExtractionJSON` şemasında diff oluşmaması için baseline schema snapshot/test eklemeyi değerlendir.

Çıkış kriteri:

- Baseline test sonucu kayıtlı.
- Etkilenecek dosyalar doğrulanmış.
- Extraction schema değişmezliği testle korunabilir durumda.

## Phase 1 — TrackingPolicy domain ve persistence

Amaç: Operasyonel takip tercihini extraction’dan ayırmak.

Yapılacaklar:

1. Tracking enum/model’lerini uygun bir schema/domain modülüne ekle.
2. `tracking_policies` tablosunu oluştur.
3. `manager_token` persistence’ını ekle.
4. Transaction creation sırasında:
   - manager token üret,
   - draft/off policy oluştur,
   - manager link döndür.
5. Physical delivery recommendation helper’ını saf fonksiyon olarak ekle.
6. Extraction tamamlandıktan sonra recommendation’ı policy’ye yaz ve event üret.
7. Recommendation helper için fiziksel ürün, hizmet, belirsiz ve çelişkili örnek testleri yaz.
8. Manager token’ın event/evidence/log’a girmediğini doğrula.

Çıkış kriteri:

- Her yeni transaction’ın draft policy’si var.
- Manager link çalışıyor.
- Extraction schema değişmedi.
- Recommendation yalnızca öneri; mode otomatik açılmıyor.

Önerilen commit sınırı:

```text
tracking policy domain + db + recommendation
```

## Phase 2 — Manager API ve policy locking

Amaç: Yetkilinin takip seçimini güvenli ve görünür biçimde yapabilmesi.

Yapılacaklar:

1. Manager view endpoint’ini ekle.
2. Policy update endpoint’ini ekle.
3. Policy lock endpoint’ini ekle.
4. Token doğrulamasını mevcut capability URL kalıbıyla uyumlu yap.
5. Contractual evidence conflict kontrolünü ekle.
6. `physical_delivery=false + tracking_mode!=off` kombinasyonunu reddet.
7. Policy locked sonrası değişikliği reddet.
8. Approval endpoint’ini policy lock şartına bağla.
9. Policy update/lock event’lerini üret.
10. Yanlış token, eksik token, locked update, conflict ve idempotent lock testlerini yaz.

Çıkış kriteri:

- Policy kilitlenmeden taraf onayı yapılamıyor.
- Tarafların onaylayacağı takip davranışı sonradan sessizce değişemiyor.
- Contractual video/e-irsaliye requirement yönetici tarafından kapatılamıyor.

Önerilen commit sınırı:

```text
manager capability + tracking policy API + lock guard
```

## Phase 3 — Effective requirements ve decision refactor

Amaç: Video ile sözleşmesel/operasyonel kanıtları doğru ayırmak.

Yapılacaklar:

1. Effective evidence resolver’ı saf fonksiyon olarak ekle.
2. Contractual, operational ve advisory kanıt kümelerini ayır.
3. Decision input’a policy/effective requirements ekle.
4. Video yokluğunun opsiyonel modda hold üretmesini kaldır.
5. Video sayımını delivered quantity fallback’i olmaktan çıkar.
6. Partial capture hesaplamasını birincil kanıta bağla.
7. Low-confidence videoyu warning olarak ele al.
8. High-confidence divergence/damage durumunu dispute yerine hold/manual review yap.
9. Decision result’a yapılandırılmış findings ekle veya eşdeğer yapı kur.
10. Saf decision test matrisi yaz.
11. Existing contractual-video davranışını koruyan test yaz.
12. `decision.py` içinde DB/network/router importu olmadığını koru.

Minimum unit test matrisi:

- policy off + no contractual evidence,
- policy off + contractual e-irsaliye,
- policy off + contractual video,
- document_only + e-irsaliye missing,
- document_only + full delivery,
- document_only + partial delivery,
- document_and_video + video missing,
- document_and_video + aligned video,
- document_and_video + low-confidence divergence,
- document_and_video + high-confidence divergence,
- document_and_video + relevant damage,
- video only,
- physical delivery false + non-off policy conflict,
- zero contract quantity,
- multiple goods.

Çıkış kriteri:

- Opsiyonel video para miktarı belirlemiyor.
- Opsiyonel video yokluğu bloklamıyor.
- Yüksek güvenli anomaly release’i durduruyor fakat dispute açmıyor.
- Contractual evidence hâlâ uygulanıyor.

Önerilen commit sınırı:

```text
effective requirements + policy-aware pure decision engine
```

## Phase 4 — Settlement coordinator ve router entegrasyonu

Amaç: Karar/ödeme orkestrasyonunu delivery router’dan çıkarıp tüm tetiklerden aynı güvenli yolla çalıştırmak.

Yapılacaklar:

1. `_attempt_decision()` benzeri I/O mantığını ayrı settlement coordinator’a taşı.
2. Coordinator:
   - extraction yüklesin,
   - policy yüklesin,
   - evidence yüklesin,
   - pure decision çağırıp sonucu işlesin,
   - release guard’ı uygulasın,
   - event’leri üretsin,
   - payment provider’ı yalnızca izinli action’da çağırsın.
3. Approvals router iki onay + pool payment sonrası coordinator’ı çağırabilsin.
4. Approval-only/no-external-evidence transaction delivery endpoint’i beklemeden ilerleyebilsin.
5. E-irsaliye endpoint’i policy/contract gereksinim guard’ı kullansın.
6. Video endpoint’i policy/contract gereksinim guard’ı kullansın.
7. Hold sonucunda capture çağrısı yapılmasın ve transaction inceleme bekleyen durumda kalsın.
8. Opsiyonel video anomaly için `dispute_opened` üretilmesin.
9. Payment provider contract’ı değişmesin.
10. Aynı event’in tekrar gönderilmesinde idempotency davranışı gözden geçirilsin; en azından ikinci release çağrısı oluşmamalı.
11. Geç gelen video ve decided state davranışı açıkça test edilsin.

Çıkış kriteri:

- Approval, e-irsaliye ve video aynı settlement orchestration yolunu kullanıyor.
- Release guard tek yerde.
- Delivery router ödeme mantığının sahibi değil.
- No-tracking approval-only senaryo takılmıyor.
- Hold/dispute semantiği ayrılmış durumda.

Önerilen commit sınırı:

```text
shared settlement coordinator + approval/delivery integration
```

## Phase 5 — Fake fixture ve demo senaryolarının düzeltilmesi

Amaç: Demo verisinin videoyu varsayılan zorunluluk gibi göstermesini engellemek.

Yapılacaklar:

1. Default fake extraction fixture’ında videoyu varsayılan required evidence olmaktan çıkar.
2. Fiziksel ürün demo sözleşmesinde varsayılan birincil teslimat kanıtı e-irsaliye olsun.
3. Opsiyonel video policy ile ayrıca etkinleştirilsin.
4. Contractual video şartını test etmek için ayrı, açık isimli fixture kullan.
5. Fake video analyzer filename ipuçları korunabilir; ancak sonuçları artık:
   - aligned,
   - low-confidence,
   - damaged/high-confidence,
   - divergent/high-confidence
   senaryolarını açıkça üretmeli.
6. Demo senaryolarını yeniden tanımla:

### Demo A — Hizmet/approval-only

- physical delivery: false
- tracking: off
- iki taraf onayı
- harici teslimat kanıtı beklenmez
- deterministik akış ilerler

### Demo B — Fiziksel mal/document-only

- physical delivery: true
- tracking: document_only
- video alanı görünmez
- e-irsaliye tam teslim → capture

### Demo C — Fiziksel mal/document+video uyumlu

- tracking: document_and_video
- video uyumlu
- e-irsaliye ana kaynak
- video supportive finding
- capture

### Demo D — Fiziksel mal/document+video anomaly

- tracking: document_and_video
- high-confidence divergence veya ilgili hasar
- hold/manual review
- release yok
- otomatik dispute yok

### Demo E — Contractual video

- sözleşme açıkça video gerektiriyor
- manager policy bunu kapatamıyor
- video eksik → hold

### Demo F — Bozuk extraction

- yüzde toplamı hatalı
- validator REJECT
- policy/approval/payment akışı başlamaz

Çıkış kriteri:

- Ana demo videosuz da anlamlı.
- Video özelliği yalnızca aktif seçildiği senaryoda görünür.
- Contractual video ile platform video tercihi ayrı test edilir.

Önerilen commit sınırı:

```text
fixtures + revised E2E scenarios
```

## Phase 6 — Frontend

Amaç: UI’da video merkezli anlatımı kaldırmak ve manager seçim akışını görünür yapmak.

Gerçek dosya yolları uygulama öncesi repo içinde doğrulanmalıdır. Değişiklikler mevcut `code/frontend/src/` sayfa/component yapısına uygulanmalıdır.

### Manager view/panel

Gösterilecekler:

- Sistem önerisi:
  - Fiziksel teslimat olası,
  - Fiziksel teslimat görünmüyor,
  - Belirsiz.
- Önerinin kısa nedenleri.
- Yönetici doğrulaması:
  - Fiziksel teslimat yok,
  - Fiziksel teslimat var.
- Takip modu:
  - Takip kapalı,
  - Yalnızca e-irsaliye,
  - E-irsaliye + yardımcı video analizi.
- Contractual evidence uyarıları.
- “Politikayı kilitle” aksiyonu.
- Kilitlemenin taraflara gösterilecek özeti.
- Video için açık metin:
  - “Video yardımcı risk sinyalidir.”
  - “Tek başına ödeme bırakmaz veya kısmi ödeme hesaplamaz.”

### Party review

Kural özetiyle birlikte:

- takip açık/kapalı,
- birincil kanıt,
- video rolü,
- sözleşmesel zorunluluklar

gösterilmelidir.

Policy kilitlenmeden approve butonu devre dışı olmalıdır.

### Transaction detail

- Video upload alanı yalnızca etkinse görünür.
- E-irsaliye aksiyonu yalnızca etkin veya contractually required ise görünür.
- Video sonucu ana karar kartı gibi gösterilmemeli.
- Video finding’leri “Yardımcı risk sinyalleri” bölümünde yer almalı.
- High-confidence anomaly durumunda:
  - “Ödeme bırakılmadı”
  - “Manuel inceleme gerekli”
  metni görünmeli.
- “Dispute açıldı” yalnızca gerçek dispute event’i varsa gösterilmeli.
- Video yüklenmemişse bunu hata olarak değil “sunulmadı” olarak göster.
- Approval-only işlemde teslimat paneli gösterilmemeli.

### Frontend error handling

Aşağıdaki 409 cevapları kullanıcıya anlaşılır gösterilmeli:

- policy locked değil,
- tracking etkin değil,
- policy locked ve değiştirilemez,
- contract-policy conflict,
- transaction already decided.

Çıkış kriteri:

- Video yalnızca manager etkinleştirince görünür.
- Taraflar takip politikasını onaydan önce görür.
- UI video sonucunu ödeme kararının sahibi gibi sunmaz.

Önerilen commit sınırı:

```text
manager policy UX + conditional delivery/video UI
```

## Phase 7 — Verification, doc-sync and plan completion

Yapılacaklar:

1. Tüm backend unit/integration/E2E testlerini çalıştır.
2. Frontend build/lint/test varsa çalıştır.
3. Manuel demo akışlarını oynat.
4. `ARCHITECTURE.md` doc-sync:
   - §1: yeni tracking/settlement modülleri,
   - §3.4: video advisory semantics,
   - §4.1: manager/policy endpoint’leri,
   - §4.3: yeni event tipleri,
   - §5: manager token, tracking table ve policy lifecycle,
   - §6: video tek başına para hareketi üretemez; policy approval öncesi kilitlenir.
5. `AGENTS.md` doc-sync:
   - yeni değişmez ilkeler,
   - manager token,
   - demo akış sırası,
   - test komutları,
   - video advisory sınırı.
6. `YOL_HARITASI.md` veya demo anlatısı video merkezliyse güncelle.
7. Frontend/backend API contract dokümanlarını güncelle.
8. Notebook veya benchmark dosyalarını değiştirme; gerekiyorsa raporda “schema unchanged” yaz.
9. Planın durum bloğunu uygula:
   - tarih,
   - test sonucu,
   - sapmalar.
10. Planı `plans/done/` altına taşı ve linkleri güncelle.

Önerilen commit sınırı:

```text
tests + docs + plan completion
```

## Files likely involved

Kesin liste uygulama öncesi repo içinde doğrulanmalıdır.

### Backend — beklenen değişiklikler

- `code/backend/app/db.py`
- `code/backend/app/schemas/extraction.py`  
  - davranış değişmez; yalnızca schema snapshot/koruma testi gerekebilir
- yeni tracking policy schema/domain modülü
- yeni physical delivery recommendation helper/service
- yeni effective requirements resolver
- `code/backend/app/services/decision.py`
- yeni settlement coordinator/service
- `code/backend/app/services/extraction.py`  
  - yalnızca fake fixture davranışı; public schema değişmez
- `code/backend/app/services/evidence.py`
- `code/backend/app/routers/transactions.py`
- `code/backend/app/routers/approvals.py`
- `code/backend/app/routers/delivery.py`
- manager/tracking router veya mevcut transaction router içindeki ilgili endpoint’ler
- `code/backend/app/schemas/events.py`
- `code/backend/app/schemas/api.py`
- `code/backend/app/config.py`  
  - yalnızca video confidence threshold gibi gerçekten gerekli ayarlar varsa
- `code/backend/.env.example`

### Tests — beklenen değişiklikler

- `code/tests/test_decision.py`
- `code/tests/test_delivery_flow.py`
- `code/tests/test_api_flow.py`
- `code/tests/test_payment_provider.py`
- yeni tracking policy test dosyası
- yeni effective requirements test dosyası
- yeni manager policy API testleri
- extraction schema compatibility/snapshot testi

### Frontend — beklenen değişiklikler

- mevcut transaction detail sayfası
- mevcut party review sayfası
- dashboard/upload sonrası link yönetimi
- API client/types
- yeni manager policy component/page
- tracking summary component
- delivery/video conditional controls

### Documentation

- `ARCHITECTURE.md`
- `AGENTS.md`
- `YOL_HARITASI.md` gerekiyorsa
- ilgili report/README metinleri
- bu plan dosyası ve `plans/README.md` linkleri gerekiyorsa

## Test plan

## Unit tests

### Tracking policy

- default policy draft/off,
- physical delivery true + off geçerli,
- physical delivery true + document_only geçerli,
- physical delivery true + document_and_video geçerli,
- physical delivery false + non-off geçersiz,
- locked policy update reddedilir,
- contract-policy conflict reddedilir,
- contractual video zorunluluğu korunur,
- recommendation manager seçimini otomatik değiştirmez.

### Physical delivery recommendation

- fiziksel adet ürünü → yes,
- koli/palet/kg → yes,
- danışmanlık/lisans → no,
- karışık hizmet + ürün → uncertain/yes gerekçeli,
- boş goods → uncertain,
- e-irsaliye required evidence → yes sinyali,
- yalnızca video sözcüğü düşük güvenli tek sinyal olarak policy açmamalı.

### Effective requirements

- off/no contract → harici requirement yok,
- off/contract e-irsaliye → e-irsaliye required,
- off/contract video → video required,
- document_only → e-irsaliye operational required,
- document_and_video → e-irsaliye required + video advisory,
- contract video + document_only → video yine contractual required,
- conflict listesi doğru.

### Decision

- video yokken document_and_video capture’ı engellemez,
- video only capture yapamaz,
- video only partial yapamaz,
- e-irsaliye full → capture,
- e-irsaliye partial → partial_capture,
- low-confidence anomaly warning,
- high-confidence divergence hold,
- matched high-confidence damage hold,
- unmatched/low-confidence damage warning,
- optional anomaly dispute üretmez,
- contractual video missing hold,
- zero quantity hold.

## API/integration tests

- create transaction manager link döner,
- manager token yanlışsa 403,
- buyer token manager endpoint’ine erişemez,
- policy update event’i oluşur,
- policy lock event’i oluşur,
- lock olmadan approval 409,
- lock sonrası approval geçer,
- lock sonrası update 409,
- tracking off iken video endpoint 409,
- tracking off iken e-irsaliye endpoint 409; contractual requirement varsa kabul,
- document_only iken video endpoint 409,
- document_and_video iken video kabul,
- decided işlemde geç video 409,
- event/evidence token içermez.

## E2E tests

1. Hizmet/approval-only/no tracking.
2. Fiziksel ürün/document-only/full delivery.
3. Fiziksel ürün/document-only/partial delivery.
4. Fiziksel ürün/document+video/aligned.
5. Fiziksel ürün/document+video/video omitted.
6. Fiziksel ürün/document+video/high-confidence anomaly → hold/no release.
7. Contractual video required/missing → hold.
8. Validator REJECT → policy/approval/payment başlamaz.
9. Policy not locked → approval rejected.
10. Wrong token paths.
11. Evidence bundle policy snapshot + event chain.
12. Repeated evidence/approval calls do not produce duplicate release.

## Manual verification flows

### Flow 1 — Hizmet sözleşmesi

1. Hizmet sözleşmesi yükle.
2. Sistem recommendation `no/uncertain`.
3. Manager physical delivery false + tracking off seçer.
4. Policy lock.
5. Party review’da teslimat/video paneli yok.
6. İki onay.
7. Harici delivery evidence beklenmediğini doğrula.

### Flow 2 — Fiziksel mal, video kapalı

1. Fiziksel ürün sözleşmesi yükle.
2. Sistem recommendation yes.
3. Manager physical delivery true + document_only.
4. Policy lock.
5. Party view video kullanmayacağını gösterir.
6. İki onay.
7. E-irsaliye gönder.
8. Video olmadan kararın ilerlediğini doğrula.

### Flow 3 — Fiziksel mal, video açık ve uyumlu

1. Manager document_and_video seçer.
2. Video yükle.
3. E-irsaliye gönder.
4. Video finding supportive.
5. Capture ratio yalnızca e-irsaliyeden.
6. Release guard ve event zinciri doğru.

### Flow 4 — Video anomaly

1. document_and_video.
2. High-confidence divergent/damaged fixture.
3. E-irsaliye + video.
4. Hold/manual review.
5. Payment provider approve çağrısı yok.
6. `dispute_opened` yok.

### Flow 5 — Contractual video

1. Açıkça video şartı olan fixture.
2. Manager videoyu kapatmayı denesin.
3. Policy lock conflict ile reddedilsin.
4. Uygun policy ile lock.
5. Video eksikse hold.

## Acceptance criteria

- `ExtractionJSON` JSON Schema çıktısı bu iş öncesiyle aynıdır.
- Notebook benchmark contract’ında değişiklik yoktur.
- Yeni transaction’larda tracking default `off` ve policy `draft` olur.
- Sistem fiziksel teslimatı yalnızca önerir; otomatik takip etkinleştirmez.
- Manager policy’yi kilitlemeden buyer/seller approval yapılamaz.
- Kilitli policy değiştirilemez.
- Party view tracking policy’yi sade biçimde gösterir.
- Tracking off olan işlemlerde video UI/endpoint devre dışıdır.
- Document-only işlem video beklemez.
- Document-and-video işlemde opsiyonel video eksikliği tek başına hold değildir.
- Video tek başına capture/partial_capture/dispute üretmez.
- Video unit count delivered quantity fallback’i değildir.
- Kısmi ödeme oranı birincil kanıttan hesaplanır.
- Low-confidence video yalnızca warning’dir.
- High-confidence anomaly hold/manual review üretir ve release çağrısı yapmaz.
- Opsiyonel video anomaly otomatik `dispute_opened` üretmez.
- Contractual video/e-irsaliye requirement manager policy tarafından devre dışı bırakılamaz.
- Approval-only/no-external-evidence işlem delivery endpoint’i beklemez.
- Decision engine saf fonksiyon olarak kalır.
- Payment release guard tek coordinator yolunda korunur.
- Event/evidence içinde capability token veya ham hassas veri bulunmaz.
- Eski ve yeni testlerin tamamı yeşildir.
- Frontend build başarılıdır.
- `ARCHITECTURE.md` ve `AGENTS.md` doc-sync tamamlanmıştır.
- Plan `done/` altına taşınmış ve durum/sapma bloğu doldurulmuştur.

## Verification commands

Repo içindeki gerçek environment yolu önce doğrulanmalıdır. Mevcut proje düzeni korunuyorsa:

```bash
cd code

# Önce mevcut baseline
./.venv/bin/python -m pytest -q

# Hedefli backend testleri
./.venv/bin/python -m pytest \
  tests/test_decision.py \
  tests/test_delivery_flow.py \
  tests/test_api_flow.py \
  -v

# Yeni tracking/policy testleri eklendikten sonra
./.venv/bin/python -m pytest \
  tests/test_tracking_policy.py \
  tests/test_effective_requirements.py \
  tests/test_manager_policy_api.py \
  -v

# Tüm suite
./.venv/bin/python -m pytest -q

# Backend manuel kontrol
./.venv/bin/uvicorn backend.app.main:app --reload
```

Frontend için gerçek script isimleri `package.json` üzerinden doğrulanarak:

```bash
npm install
npm run build
npm run lint
npm test
```

Yalnızca mevcut script’ler çalıştırılmalı; olmayan script uydurulmamalıdır.

## Suggested commit sequence

1. `feat: add tracking policy domain and persistence`
2. `feat: add manager policy configuration and locking`
3. `refactor: separate effective evidence requirements from extraction`
4. `refactor: make decision engine tracking-policy aware`
5. `refactor: centralize settlement orchestration`
6. `fix: make video advisory and remove quantity fallback`
7. `test: revise delivery and settlement scenarios`
8. `feat: add manager tracking policy UI`
9. `docs: sync optional delivery tracking architecture`

Commit sayısı Codex tarafından makul biçimde birleştirilebilir; ancak domain/persistence, decision refactor ve UI tek dev commit’e yığılmamalıdır.

## Risks and mitigations

### Risk 1 — Kapsamın milestone engine rewrite’a dönüşmesi

Mitigation:

- Bu plan yalnızca harici evidence gerekmeyen approval-only akışın takılmamasını düzeltir.
- Tam çok-aşamalı ödeme yürütümü ayrı plan olarak bırakılır.
- Payment rule yüzdelerinin parça parça ledger’a uygulanması bu planın zorunlu kabul kriteri değildir.

### Risk 2 — Contractual ve operational evidence yeniden karışabilir

Mitigation:

- Tek effective requirements resolver.
- Contractual/operational/advisory kümeleri ayrı.
- UI ve evidence bundle aynı ayrımı gösterir.
- Unit testler conflict senaryolarını kapsar.

### Risk 3 — Manager token yeni güvenlik yüzeyi açar

Mitigation:

- Mevcut capability URL kalıbı kullanılır.
- `secrets.token_urlsafe(32)`.
- Token log/event/evidence’a girmez.
- Yanlış rol token’ları endpoint bazında 403.
- Tam auth kapsam dışı olduğu dokümante edilir.

### Risk 4 — Mevcut SQLite runtime DB kırılabilir

Mitigation:

- Additive, idempotent init/migration.
- Test DB’lerinde temiz şema.
- Demo DB reset gerekiyorsa açık manuel adım; sessiz veri silme yok.
- Migration testi.

### Risk 5 — Video gelmeden e-irsaliye kararı tamamlanabilir

Bu, videonun gerçekten opsiyonel olmasının doğal sonucudur.

Mitigation:

- UI, video kullanılacaksa karar öncesi yüklenmesi gerektiğini yöneticinin akışında açıkça gösterir.
- Video yokluğu bloklayıcı değildir.
- Karar verilmiş işlemde geç video kabul edilmez.
- Gelecekte grace period/explicit evaluate action ayrı plan olabilir; bu planda timer/queue eklenmez.

### Risk 6 — Video false positive’leri gereksiz hold üretebilir

Mitigation:

- Confidence threshold.
- Hasar sinyalinde ilgili kutu/paket eşleşmesi.
- Düşük confidence warning.
- Video asla doğrudan dispute/release yapmaz.
- Threshold tek yerde tutulur ve testlenir.

### Risk 7 — UI policy’yi gizler veya teknik gösterir

Mitigation:

- Party view kabul kriteri.
- Sade Türkçe tracking summary.
- Video rolü açıkça “yardımcı risk sinyali”.
- Approve butonu policy görünmeden aktif olmaz.

### Risk 8 — Existing E2E “dispute” demosu kaybolur

Bu bilinçli bir semantik düzeltmedir: video modelinin otomatik dispute açması güvenli değildir.

Mitigation:

- Video anomaly demosu “hold + manual review + release yok” olarak güncellenir.
- Gerçek dispute açma/çözme akışı ayrı manager-review planına taşınır.
- Dokümantasyonda davranış değişikliği açıkça belirtilir.

## Follow-up plans explicitly deferred

Bu iş tamamlandıktan sonra ayrı planlar olarak ele alınabilir:

1. Çok aşamalı milestone ödeme ledger’ı.
2. Manager manual review resolution:
   - continue,
   - request new evidence,
   - dispute,
   - cancel/refund.
3. Policy amendment + party re-approval.
4. Gerçek e-irsaliye doğrulama adapter’ı.
5. Video grace period veya explicit settlement evaluation.
6. Tam kullanıcı/RBAC sistemi.
7. Gerçek Moka provider.
8. Birden fazla video/fotoğrafın güvenli birleştirilmesi ve double-count önleme.

## Notes for Codex implementer

- Önce `AGENTS.md`, `ARCHITECTURE.md`, bu plan ve mevcut ilgili testleri oku.
- Plan ile mimari çelişirse sessizce karar verme; en küçük tutarlı tasarımı seç ve sapmayı raporla.
- `ExtractionJSON` şemasını değiştirme.
- Notebook dosyasını değiştirme.
- RAG/LLM prompt’una manager policy seçtirme.
- Video modeline para/dispute yetkisi verme.
- `decision.py` saf fonksiyon sınırını koru.
- Payment release guard’ı zayıflatma.
- Contractual evidence manager tercihiyle silinemez.
- Token’ları loglama veya event/evidence içine yazma.
- Yeni endpoint ve event’leri `ARCHITECTURE.md` ile aynı commit dalgasında senkronla.
- Her fazdan sonra hedefli test çalıştır; yalnızca en sonda tüm suite’e güvenme.
- Mevcut frontend dosya yollarını doğrulamadan isim/path uydurma.
- Eski testleri sadece yeni doğru semantiğe aykırı olduklarında güncelle; testleri geçmek için güvenlik kontrollerini gevşetme.
- Hold ve dispute kavramlarını aynılaştırma.
- Video missing, video low-confidence ve video anomaly durumlarını ayrı kodlarla temsil et.
- Uygulama sonunda:
  - test sonuçlarını,
  - schema değişmezliğini,
  - API değişikliklerini,
  - migration davranışını,
  - sapmaları
  raporla.
- Doc-sync tamamlanmadan işi bitmiş sayma.
