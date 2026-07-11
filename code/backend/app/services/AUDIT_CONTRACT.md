# Audit / Business Event Ayrım Kontratı (Plan 02 kontrat, Plan 03 / Faz 3B implementasyon)

> Bu doküman `ARCHITECTURE.md`/`AGENTS.md`'nin yerine geçmez; global doc-sync
> yapılmaz (o, integration checkpoint'te Berke'nin işidir). Yalnız
> `services/audit.py`'nin kontratını açıklar.
>
> **Durum (2026-07-11, Plan 03 / Faz 3B):** `audit_events` tablosu migration
> `006`'da gerçek olarak var (registry kaydı Berke'nin entegrasyon commit'i);
> `record()` artık `NotImplementedError` değil, gerçek `INSERT` yapar. Aşağıdaki
> kurallar değişmedi — yalnız "henüz tablo yok" iskelet notu güncel değil.

## Neden ayrı bir kavram

`events` tablosu (§4.3) **business event bus**'tır: kanıt zinciri, evidence
bundle ve UI timeline'ı bundan beslenir. Audit event ise **kim ne yaptı**
sorusuna cevap veren, güvenlik/uyumluluk amaçlı ayrı bir kayıttır. İkisi
karıştırılırsa: (a) business event payload'ları bugün token/PII taşımadığı
varsayımıyla yazılıyor — audit'in ihtiyaç duyduğu actor kimliği bu varsayımı
bozar; (b) evidence bundle üretimi audit gürültüsüyle kirlenir.

## Kural 1 — Aynı connection, aynı transaction

`audit.record(conn, ...)` çağırana ait `conn`'u kullanır. Kendi
`sqlite3.connect()` çağırmaz, kendi `commit()`/`rollback()` çağırmaz. Böylece
audit yazımı, onu tetikleyen business mutation'la **atomik**tir: mutation
rollback olursa audit kaydı da geri alınır, ayrı bir "audit'i her ne olursa
olsun yaz" mekanizması yoktur (bu bilinçli bir tercihtir — audit,
gerçekleşmemiş bir aksiyonu iddia etmemelidir).

## Kural 2 — Allowlist zorunlu

`metadata_allowlist` parametresi olmadan hiçbir ek alan kabul edilmez.
Çağıran, o `action` için hangi metadata alanlarının audit'e girebileceğini
açıkça listeler; listede olmayan bir anahtar `DisallowedMetadataError`
fırlatır. Bu, "birisi ileride debug amaçlı tüm request body'sini metadata'ya
koyar" sınıfı hataları derleme zamanında değil ama ilk çağrıda yakalar.

## Kural 3 — Token/secret/PII yasak (savunma derinliği)

Allowlist'te olsa bile anahtar adı `token`/`password`/`secret`/`checkkey`/
`card`/`pan`/`cvc`/`cvv`/`tckn`/`vkn`/`iban` örüntülerinden birini içeriyorsa
reddedilir. Bu, yalnızca "allowlist'i doğru yaz" disiplinine güvenmek yerine
ikinci bir otomatik bariyerdir.

## Kural 4 — `events` tablosuna sessiz yazım yok

`record()` her zaman `audit_events`'e yazar; legacy `events` tablosuna hiçbir
koşulda audit satırı sızdırmaz. `target` parametresi `"tip:id"` biçiminde tek
bir string'tir (örn. `"transaction:abc123"`) ve `target_type`/`target_id`
kolonlarına güvenli şekilde ayrıştırılır (`InvalidAuditTargetError` ile
fail-closed, colon yoksa veya tip/id boşsa reddedilir). `metadata_json`
her zaman **stable sorted JSON**'dır (`json.dumps(..., sort_keys=True)`) —
aynı metadata her zaman aynı byte dizisini üretir (diff/karşılaştırma
kolaylığı, gizli alan sızıntısı riski azaltma).

## Sahiplik

Kontrat (imza + kurallar + testler) Plan 02'de Yusuf tarafından donar.
Implementasyon (migration 006 + gerçek INSERT) Plan 03'ten itibaren Yusuf'un
kendi domain'i olan participants/audit/review/evidence/dispute servisleri
kapsamında ilerler (bkz. program_haritasi §3 hot-file tablosu).
