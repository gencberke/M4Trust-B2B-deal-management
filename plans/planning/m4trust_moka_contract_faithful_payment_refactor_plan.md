# M4Trust — Moka Public Pool Payment Contract Uyumlu Ödeme Refactor Planı

> **Durum:** Planlama taslağı — 2026-07-10  
> **Ana plan ilişkisi:** `m4trust_stratejik_domain_evrimi_programi_v2.md` içindeki yalnızca Moka/payment, funding-unit, milestone release, mock ledger, payment adapter ve ilgili test/wave bölümlerini değiştirir. Identity, invitation, rule versioning, ratification, review, evidence ve genel authorization kararları aynen korunur.  
> **Kaynak sözleşme:** Moka United herkese açık `PaymentDealer` dokümantasyonu  
> **Contract profile:** `moka_payment_dealer_pool_v1`  
> **Demo hedefi:** M4Trust backend'in gerçek bir HTTP istemcisiyle, ayrı çalışan yerel Moka mock servisine Moka'nın yayımlanmış endpoint, request ve response şekilleriyle istek atması  
> **Production hedefi:** Aynı HTTP client ve contract modellerinin yalnız base URL ve credentials değiştirilerek Moka test/canlı ortamına yönlendirilebilmesi  
> **Önemli sınır:** Sandbox/canlı Moka hesabıyla doğrulama yapılmadan “gerçek Moka entegrasyonu tamamlandı” denmez. Demo, public contract-faithful mock olarak sunulur.

---

# 1. Neden bu refactor gerekli?

Önceki master plan aşağıdaki varsayımı taşıyordu:

```text
tek pool payment
→ capture_ratio ile kısmi release
→ aynı ödeme üzerinde birden fazla milestone release
```

Moka'nın public `PaymentDealer` pool-payment contract'ı bunu tanımlamıyor.

Public contract'ta:

```text
POST /PaymentDealer/DoDirectPayment
PaymentDealerRequest.IsPoolPayment = 1
```

ile sabit tutarlı bir havuz ödemesi oluşturuluyor.

Daha sonra:

```text
POST /PaymentDealer/DoApprovePoolPayment
```

yalnız:

```text
VirtualPosOrderId
veya
OtherTrxCode
```

alarak ödeme kaydını onaylıyor.

Approve isteğinde:

- amount,
- partial amount,
- capture ratio,
- remaining amount

alanı bulunmuyor.

Bu nedenle bu plan şu bağlayıcı kararı getirir:

> **Bir Moka pool payment kaydı tek, bölünemez bir funding unit'tir ve en fazla bir kez bütünüyle approve edilir.**

Kısmi veya çok aşamalı ödeme:

```text
aynı pool payment'ı parça parça approve etmek
```

ile değil,

```text
önceden belirlenmiş birden fazla funding unit
→ her unit için ayrı pool payment
→ her unit için ayrı approve
```

ile modellenir.

---

# 2. Public Moka contract'tan alınan bağlayıcı gerçekler

## 2.1 Ortamlar

Public dokümanda:

```text
Test:
https://service.refmokaunited.com

Production:
https://service.mokaunited.com
```

tanımlıdır.

Servisler:

- JSON,
- HTTP POST,
- TLS 1.2+

ile çağrılır.

## 2.2 Ortak ApiResponse zarfı

Başarılı veya başarısız bütün mock cevapları şu üst zarfı korur:

```json
{
  "Data": {},
  "ResultCode": "Success",
  "ResultMessage": "",
  "Exception": null
}
```

Provider-level request/auth/validation hatasında:

```json
{
  "Data": null,
  "ResultCode": "PaymentDealer....",
  "ResultMessage": "",
  "Exception": null
}
```

Beklenmeyen hatada:

```json
{
  "Data": null,
  "ResultCode": "EX",
  "ResultMessage": "...",
  "Exception": "..."
}
```

Moka'da iki hata katmanı vardır:

### Envelope/provider katmanı

```text
ApiResponse.ResultCode != Success
Data == null
```

### İşlem/banka katmanı

```text
ApiResponse.ResultCode == Success
Data.IsSuccessful == false
Data.ResultCode / Data.ResultMessage dolu
```

Mock bu iki hata türünü birbirine karıştırmaz.

## 2.3 Authentication contract

Her endpoint:

```json
"PaymentDealerAuthentication": {
  "DealerCode": "...",
  "Username": "...",
  "Password": "...",
  "CheckKey": "..."
}
```

bloğunu alır.

CheckKey:

```text
SHA-256(
    DealerCode
    + "MK"
    + Username
    + "PD"
    + Password
)
```

Mock server bu formülü doğrular.

## 2.4 Pool payment oluşturma

Endpoint:

```text
POST /PaymentDealer/DoDirectPayment
```

M4Trust standard profile için kullanılan alanlar:

```text
PaymentDealerAuthentication

PaymentDealerRequest
- CardHolderFullName
- CardToken
- Amount
- Currency
- InstallmentNumber
- ClientIP
- OtherTrxCode
- IsPoolPayment = 1
- IsTokenized = 0
- Software
- Description
- IsPreAuth = 0
- BuyerInformation optional
```

Demo:

- gerçek PAN/CVC kullanmaz,
- `CardToken` benzeri demo token kullanır,
- CardNumber, ExpMonth, ExpYear ve CvcNumber boş bırakılır,
- mock tokenı doğrular,
- request veya trace içinde token maskelenir.

Başarılı cevap:

```json
{
  "Data": {
    "IsSuccessful": true,
    "ResultCode": "",
    "ResultMessage": "",
    "VirtualPosOrderId": "ORDER-DEMO-..."
  },
  "ResultCode": "Success",
  "ResultMessage": "",
  "Exception": null
}
```

## 2.5 Pool payment approve

Endpoint:

```text
POST /PaymentDealer/DoApprovePoolPayment
```

İstek:

```text
VirtualPosOrderId
veya
OtherTrxCode
```

Approve işlemine amount gönderilmez.

Mock en az şu public error code'ları üretir:

```text
PaymentDealer.CheckPaymentDealerAuthentication.InvalidRequest
PaymentDealer.CheckPaymentDealerAuthentication.InvalidAccount
PaymentDealer.CheckPaymentDealerAuthentication.VirtualPosNotFound
PaymentDealer.DoApprovePoolPayment.OtherTrxCodeOrVirtualPosOrderIdMustGiven
PaymentDealer.DoApprovePoolPayment.DealerPaymentNotFound
PaymentDealer.DoApprovePoolPayment.PaymentAlreadyApproved
PaymentDealer.DoApprovePoolPayment.PaymentIsNotPoolPayment
EX
```

## 2.6 Pool approval undo

Endpoint:

```text
POST /PaymentDealer/UndoApprovePoolPayment
```

İstek:

```text
VirtualPosOrderId
veya
OtherTrxCode
```

Public dokümana göre onay iptali bayi ekstresi/gün sonu oluşmadan önce yapılabilir.

Mock en az şu error code'ları üretir:

```text
PaymentDealer.CheckPaymentDealerAuthentication.InvalidRequest
PaymentDealer.UndoApprovePoolPayment.DealerPaymentNotFound
PaymentDealer.UndoApprovePoolPayment.OtherTrxCodeAndVirtualPosOrderIdNotMatch
PaymentDealer.UndoApprovePoolPayment.OtherTrxCodeOrVirtualPosOrderIdMustGiven
PaymentDealer.UndoApprovePoolPayment.PaymentNotApprovedYet
PaymentDealer.UndoApprovePoolPayment.PaymentIsNotPoolPayment
PaymentDealer.UndoApprovePoolPayment.PaymentNotApprovedYetForSubDealer
EX
```

Demo mock'ta:

```text
statement_closed = false
```

iken undo yapılabilir.

```text
statement_closed = true
```

iken public dokümanda exact code tanımlanmadığı için mock yeni bir Moka code icat etmez. Bu durum test-only fault configuration veya internal operation failure olarak tutulur ve M4Trust review/reconciliation katmanına yansıtılır.

## 2.7 Payment detail query

Reconciliation için:

```text
POST /PaymentDealer/GetDealerPaymentTrxDetailList
```

kullanılır.

İstek:

```text
PaymentId
veya
OtherTrxCode
```

M4Trust bilinmeyen create sonucunu `OtherTrxCode` ile sorgular.

Ödeme ana durumları:

```text
PaymentStatus 0 / TrxStatus 0
→ ödeme onayı bekliyor

PaymentStatus 2 / TrxStatus 1
→ ödeme başarılı

PaymentStatus 3 / TrxStatus 1
→ iptal başarılı

PaymentStatus 4 / TrxStatus 1
→ tam iade başarılı
```

Internal domain statüsü ile Moka numeric statüsü birbirinden ayrılır.

---

# 3. Bağlayıcı mimari kararları

## 3.1 Public contract source of truth

Varsayılan profile:

```text
moka_payment_dealer_pool_v1
```

Public dokümana göre uygulanır.

Mock'a dokümante edilmemiş şu davranışlar eklenmez:

- partial pool approval,
- capture ratio,
- same payment multiple approve,
- undocumented wallet balance behavior,
- undocumented escrow split.

## 3.2 Standard ve marketplace ayrımı

Bu planın varsayılanı:

```text
standard PaymentDealer pool payment
```

profilidir.

Public portalda ayrıca marketplace contract vardır:

```text
/PaymentDealer/DoDirectPaymentMarketPlace
SubDealer[]
```

Ancak bu profil:

- Moka marketplace/subdealer sözleşmesi,
- seller DealerId onboarding,
- commission scenario,
- marketplace credentials

gerektirir.

Bu nedenle mevcut demo scope'una alınmaz.

Extension point:

```text
moka_marketplace_pool_v1
```

ayrı bir adapter profile olarak daha sonra eklenebilir.

Standart ve marketplace payload'ları tek modelde karıştırılmaz.

## 3.3 Bir funding unit = bir pool payment

```text
FundingUnit
1:1
ProviderPayment
```

Her provider payment:

- sabit amount,
- sabit currency,
- unique OtherTrxCode,
- tek VirtualPosOrderId,
- tek pool approve

taşır.

## 3.4 Milestone ile funding unit aynı şey değildir

```text
Milestone
= ticari şart / iş adımı

FundingUnit
= provider'ın tek seferde tuttuğu ve tek seferde approve ettiği sabit para parçası
```

Bir milestone:

```text
1 funding unit
```

veya:

```text
N fixed tranche funding unit
```

üretebilir.

## 3.5 Arbitrary proportional release Moka profile'da yasak

Master plandaki generic:

```text
proportional_to_verified_quantity
```

semantiği platform seviyesinde korunabilir.

Ancak Moka profile seçiliyken ratification package açılmadan önce finite bir funding schedule'a compile edilmelidir.

Kabul edilen Moka schedule mode'ları:

```text
all_or_nothing
fixed_tranches
```

Örnek:

```text
Teslimat milestone'u: 40.000 TRY

Tranche 1:
- 25 birim doğrulanınca
- 10.000 TRY

Tranche 2:
- toplam 50 birim doğrulanınca
- 10.000 TRY

Tranche 3:
- toplam 75 birim doğrulanınca
- 10.000 TRY

Tranche 4:
- toplam 100 birim doğrulanınca
- 10.000 TRY
```

Her tranche ayrı pool payment olur.

Şu plan Moka profile ile ratifiable değildir:

```text
teslim edilen her rastgele miktar kadar anlık release
```

Çünkü approve anında tutar gönderilemez ve pool payment amount'u önceden sabittir.

Hata:

```text
PROVIDER_CAPABILITY_CONFLICT
MOKA_REQUIRES_FIXED_FUNDING_UNITS
```

## 3.6 Tüm para baştan havuzda tutulacaksa

Ratification tamamlandığında:

```text
FundingCoordinator
→ bütün funding unit'ler için pool payment oluşturur
```

Transaction ancak bütün gerekli funding unit'ler:

```text
pool_created
```

olduğunda:

```text
active
```

durumuna geçer.

Bu, toplam fonun başlangıçta pool'da tutulmasını korur.

## 3.7 Kısmi funding başarısızlığı

Örneğin 4 unit'ten:

```text
3 pool_created
1 failed
```

olursa:

```text
transaction = funding_pending / funding_review_required
```

olur.

Release yapılamaz.

Retry:

- aynı funding unit,
- aynı OtherTrxCode,
- önce reconciliation,
- kör yeniden create yok

kuralıyla yürür.

Compensation/cancel:

- demo minimumunda manual review,
- payment hardening aşamasında automatic cancellation policy

olarak ele alınır.

---

# 4. Demo topolojisi

## 4.1 İki ayrı HTTP servisi

### M4Trust API

```text
http://127.0.0.1:8000
```

### Local Moka Contract Mock

```text
http://127.0.0.1:8001
```

M4Trust gerçek HTTP POST atar.

Bu sayede demo:

- in-process fake method call değil,
- gerçek network boundary,
- JSON serialization,
- timeout,
- HTTP status,
- provider response parsing

gösterir.

## 4.2 Çalıştırma

Terminal 1:

```bash
cd code
uvicorn backend.mock_moka.app:app --port 8001
```

Terminal 2:

```bash
cd code
PAYMENT_PROVIDER=moka_http \
MOKA_BASE_URL=http://127.0.0.1:8001 \
uvicorn backend.app.main:app --port 8000
```

## 4.3 Ortam değişimi

### Unit test

```text
PAYMENT_PROVIDER=fake
```

Saf ve hızlı fake.

### Contract/integration test

```text
PAYMENT_PROVIDER=moka_http
MOKA_BASE_URL=ASGITransport(mock_moka_app)
```

Gerçek HTTP contract path, ağsız test.

### Demo

```text
PAYMENT_PROVIDER=moka_http
MOKA_BASE_URL=http://127.0.0.1:8001
```

Ayrı process ve gerçek localhost HTTP.

### Moka sandbox

```text
PAYMENT_PROVIDER=moka_http
MOKA_BASE_URL=https://service.refmokaunited.com
```

### Production

```text
PAYMENT_PROVIDER=moka_http
MOKA_BASE_URL=https://service.mokaunited.com
```

Kod yolu değişmez.

Credentials ve payment token kaynağı değişir.

---

# 5. Modül yapısı

```text
code/backend/
├── app/
│   ├── services/
│   │   └── payments/
│   │       ├── ports.py
│   │       ├── domain.py
│   │       ├── funding_plan.py
│   │       ├── funding_coordinator.py
│   │       ├── release_coordinator.py
│   │       ├── reconciliation.py
│   │       └── moka/
│   │           ├── contracts.py
│   │           ├── authentication.py
│   │           ├── serialization.py
│   │           ├── client.py
│   │           ├── mapper.py
│   │           ├── errors.py
│   │           └── redaction.py
│   ├── repositories/
│   │   ├── funding_units.py
│   │   ├── provider_payments.py
│   │   ├── release_instructions.py
│   │   └── payment_attempts.py
│   └── schemas/
│       └── payments.py
│
└── mock_moka/
    ├── app.py
    ├── config.py
    ├── db.py
    ├── contracts.py
    ├── authentication.py
    ├── service.py
    ├── repository.py
    ├── status_mapper.py
    ├── fault_injection.py
    └── tests/
```

## 5.1 Contract model duplication kuralı

Moka public JSON contract modelleri tek package'ta tanımlanır:

```text
backend/app/services/payments/moka/contracts.py
```

Mock server bu modelleri import edebilir.

Ancak mock business implementation ile M4Trust domain implementation aynı kodu paylaşmaz.

Amaç:

```text
aynı DTO contract
farklı provider/server davranışı
```

---

# 6. Payment port refactor

Mevcut:

```python
approve_pool_payment(
    other_trx_code,
    capture_ratio=...
)
```

kaldırılır.

Yeni port:

```python
class PaymentGateway(Protocol):
    def create_pool_payment(
        self,
        command: CreatePoolPaymentCommand,
    ) -> CreatePoolPaymentResult:
        ...

    def approve_pool_payment(
        self,
        identifier: ProviderPaymentIdentifier,
    ) -> ProviderOperationResult:
        ...

    def undo_pool_approval(
        self,
        identifier: ProviderPaymentIdentifier,
    ) -> ProviderOperationResult:
        ...

    def get_payment_detail(
        self,
        query: PaymentDetailQuery,
    ) -> PaymentDetailResult:
        ...
```

`capture_ratio` provider interface'inde bulunmaz.

## 6.1 Provider capability profile

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    supports_pool_payment: bool
    supports_partial_pool_approval: bool
    supports_multiple_approvals_per_payment: bool
    supports_approval_undo: bool
    supports_fixed_tranches: bool
    supports_marketplace_subdealers: bool
```

Moka standard profile:

```text
supports_pool_payment = true
supports_partial_pool_approval = false
supports_multiple_approvals_per_payment = false
supports_approval_undo = true
supports_fixed_tranches = true
supports_marketplace_subdealers = false
```

Ratification/funding-plan validator bu capability profile'ı kullanır.

---

# 7. Moka HTTP client

## 7.1 Responsibilities

`MokaPaymentDealerClient`:

- CheckKey üretir,
- exact request envelope kurar,
- JSON POST yapar,
- timeout uygular,
- ApiResponse parse eder,
- provider/envelope failure ayrımı yapar,
- response contract validation yapar,
- redacted trace üretir.

Yapmaz:

- transaction authorization,
- milestone eligibility,
- release kararı,
- retry policy kararı,
- DB commit.

## 7.2 HTTP ayarları

```text
connect timeout: 5s
read timeout: 20s
total retry:
- GET/detail query safe retry
- create/approve blind retry yok
```

Create veya approve timeout'unda:

```text
unknown_result
→ reconciliation
```

oluşur.

## 7.3 Currency mapping

Internal:

```text
TRY
USD
EUR
```

Moka boundary:

```text
TL
USD
EUR
```

Mapper:

```text
TRY → TL
TL → TRY
```

Unsupported currency:

```text
PROVIDER_UNSUPPORTED_CURRENCY
```

## 7.4 Amount serialization

Internal:

```text
amount_minor INTEGER
```

Boundary:

```text
Decimal(amount_minor) / 100
```

JSON numeric decimal olarak gönderilir.

Binary float doğrudan source of truth değildir.

Önerilen serializer:

```text
simplejson with use_decimal=True
```

veya contract testlerle doğrulanmış custom JSON encoder.

---

# 8. Demo-safe card/payment method yaklaşımı

## 8.1 Raw card data yok

M4Trust:

- PAN,
- CVC,
- expiry

persist etmez veya loglamaz.

Demo request:

```text
CardToken = MOKA_DEMO_CARD_TOKEN
```

kullanır.

Mock:

- belirli demo tokenları kabul eder,
- invalid token ile bank-level failure üretebilir.

## 8.2 Production boundary

Gerçek entegrasyon:

- Moka CardToken,
- hosted/common payment page,
- PCI uyumlu ayrı kart toplama akışı

gerektirir.

Bu plan raw card formunu M4Trust backend'e eklemez.

## 8.3 Trace redaction

Trace panelinde:

```text
Password → ***
CheckKey → first6...last4
CardToken → token_****1234
ClientIP → masked/optional
Buyer email/phone → masked
```

gösterilir.

---

# 9. Funding plan refactor

## 9.1 Yeni kavram: FundingPlan

Ratification package içinde provider-compatible funding schedule bulunur.

```text
FundingPlan
- provider_profile
- package_id
- total_amount_minor
- currency
- funding_units[]
```

## 9.2 FundingUnit

```text
FundingUnit
- id
- transaction_id
- ratification_package_id
- milestone_id
- sequence
- title
- amount_minor
- currency
- eligibility_type
- eligibility_payload
- other_trx_code
- provider_profile
- status
```

Status:

```text
planned
pool_creation_pending
pool_created
pool_creation_unknown
pool_creation_failed
approval_pending
approval_unknown
approved
approval_undo_pending
approval_undone
cancelled
refunded
```

## 9.3 OtherTrxCode formatı

Deterministik ve kısa:

```text
M4T-{tx8}-P{package_version}-U{unit_sequence}
```

Örnek:

```text
M4T-a91c2d3e-P2-U04
```

Constraint:

```text
UNIQUE(provider_profile, other_trx_code)
```

Retry yeni OtherTrxCode üretmez.

Yeni package version yeni code üretir.

## 9.4 Funding unit compiler

### All-or-nothing

```text
milestone amount
→ one funding unit
```

### Fixed tranches

```text
milestone amount
→ N predetermined funding units
```

Tranche toplamı milestone amount'a tam eşit olmalıdır.

Largest-remainder yalnız unit amount dağıtımında kullanılır.

## 9.5 Ratification package etkisi

Package şu alanları içerir:

```text
provider_profile
funding_schedule
funding unit sequence
amounts
currency
eligibility thresholds
OtherTrxCode derivation version
```

Funding schedule değişirse:

```text
package superseded
→ re-ratification
```

---

# 10. Funding lifecycle

## 10.1 Trigger

```text
current package complete
AND buyer ratified
AND seller ratified
AND no blocking review
```

olduğunda:

```text
FundingCoordinator.ensure_pool_payments()
```

çalışır.

## 10.2 Her unit için create

M4Trust gönderir:

```json
{
  "PaymentDealerAuthentication": {
    "DealerCode": "DEMO-DEALER",
    "Username": "demo-user",
    "Password": "*** runtime only ***",
    "CheckKey": "..."
  },
  "PaymentDealerRequest": {
    "CardHolderFullName": "Demo Buyer",
    "CardNumber": "",
    "ExpMonth": "",
    "ExpYear": "",
    "CvcNumber": "",
    "CardToken": "DEMO-TOKEN",
    "Amount": 2500.00,
    "Currency": "TL",
    "InstallmentNumber": 1,
    "ClientIP": "127.0.0.1",
    "OtherTrxCode": "M4T-a91c2d3e-P2-U01",
    "SubMerchantName": "",
    "IsPoolPayment": 1,
    "IsTokenized": 0,
    "IntegratorId": 0,
    "Software": "M4Trust",
    "Description": "M4Trust funding unit U01",
    "IsPreAuth": 0
  }
}
```

## 10.3 Başarı

Response parse edilir:

```text
ResultCode == Success
Data.IsSuccessful == true
VirtualPosOrderId present
```

DB:

```text
funding_unit.status = pool_created
provider_payment.payment_status = pool_waiting
VirtualPosOrderId saved
```

## 10.4 Bank-level failure

```text
ResultCode == Success
Data.IsSuccessful == false
```

DB:

```text
pool_creation_failed
provider result code/message
```

Review case:

```text
PAYMENT_POOL_CREATION_FAILED
```

## 10.5 Provider-level failure

```text
ResultCode != Success
Data == null
```

mapped error kaydedilir.

## 10.6 Timeout/unknown

Create HTTP timeout:

```text
pool_creation_unknown
```

Kör retry yok.

Önce:

```text
GetDealerPaymentTrxDetailList
OtherTrxCode
```

ile reconciliation.

- found pending → `pool_created`
- found successful/approved → mapped status
- not found → controlled retry
- ambiguous → manual review

## 10.7 Transaction activation

Bütün required funding units:

```text
pool_created
```

olmadan transaction:

```text
funding_pending
```

kalır.

Tümü oluşunca:

```text
active
```

olur.

---

# 11. Release lifecycle

## 11.1 Eligibility

Milestone/evidence engine yalnız funding unit'i:

```text
eligible_for_approval
```

yapar.

Provider çağrısını doğrudan yapmaz.

## 11.2 Release instruction

```text
release_instruction
- funding_unit_id
- provider_payment_id
- operation approve_pool_payment
- idempotency_key
- status
```

Bir unit için tek aktif approve instruction:

```text
UNIQUE(funding_unit_id, operation_type)
```

## 11.3 Approve request

```json
{
  "PaymentDealerAuthentication": {
    "DealerCode": "DEMO-DEALER",
    "Username": "demo-user",
    "Password": "*** runtime only ***",
    "CheckKey": "..."
  },
  "PaymentDealerRequest": {
    "VirtualPosOrderId": "ORDER-DEMO-000001",
    "OtherTrxCode": ""
  }
}
```

Tercih:

- create response'tan VirtualPosOrderId varsa onu kullan,
- fallback/reconciliation için OtherTrxCode sakla.

## 11.4 Approve success

```text
ResultCode == Success
Data.IsSuccessful == true
```

sonucu:

```text
funding_unit = approved
milestone aggregate recalculated
release_instruction = confirmed
```

## 11.5 PaymentAlreadyApproved

Bu error otomatik “failure” sayılmaz.

Akış:

```text
PaymentAlreadyApproved
→ detail reconciliation
→ provider gerçekten approved ise
   local confirmed
→ değilse review
```

## 11.6 Undo approval

Undo yalnız açık policy/authorized reviewer aksiyonuyla çağrılır.

Otomatik anomaly:

```text
approve
→ sonra undo
```

yapmaz.

Undo:

- settlement reversal policy,
- provider cutoff,
- dispute resolution

ile açıkça ilişkilendirilir.

---

# 12. Internal ve provider state ayrımı

## 12.1 Internal ProviderPaymentState

```text
create_pending
pool_waiting
approved
approval_undone
cancelled
refunded
failed
unknown
```

## 12.2 Moka numeric state

Mock detail/list response:

```text
Pool awaiting approval:
PaymentStatus = 0
TrxStatus = 0

Approved payment:
PaymentStatus = 2
TrxStatus = 1

Cancelled:
PaymentStatus = 3
TrxStatus = 1

Fully refunded:
PaymentStatus = 4
TrxStatus = 1
```

Mapper tek modülde yaşar:

```text
moka/status_mapper.py
```

Internal enum API response'a Moka numeric code diye sızdırılmaz.

---

# 13. Veritabanı şeması refactor'ı

## 13.1 M4Trust application DB

### `funding_units`

```text
id TEXT PRIMARY KEY
transaction_id TEXT NOT NULL
ratification_package_id TEXT NOT NULL
milestone_id TEXT NOT NULL
sequence INTEGER NOT NULL
title TEXT NOT NULL
amount_minor INTEGER NOT NULL
currency TEXT NOT NULL
eligibility_type TEXT NOT NULL
eligibility_payload_json TEXT NOT NULL
provider_profile TEXT NOT NULL
other_trx_code TEXT NOT NULL
status TEXT NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL

UNIQUE(provider_profile, other_trx_code)
UNIQUE(ratification_package_id, sequence)
CHECK(amount_minor > 0)
```

### `provider_payments`

```text
id TEXT PRIMARY KEY
funding_unit_id TEXT NOT NULL UNIQUE
provider_profile TEXT NOT NULL
other_trx_code TEXT NOT NULL
virtual_pos_order_id TEXT
dealer_payment_id TEXT
internal_status TEXT NOT NULL
moka_payment_status INTEGER
moka_trx_status INTEGER
amount_minor INTEGER NOT NULL
currency TEXT NOT NULL
last_result_code TEXT
last_result_message TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL

UNIQUE(provider_profile, other_trx_code)
UNIQUE(provider_profile, virtual_pos_order_id)
```

### `provider_operations`

```text
id TEXT PRIMARY KEY
provider_payment_id TEXT
funding_unit_id TEXT NOT NULL
operation_type TEXT NOT NULL
endpoint TEXT NOT NULL
idempotency_key TEXT NOT NULL
request_fingerprint TEXT NOT NULL
redacted_request_json TEXT NOT NULL
response_json TEXT
http_status INTEGER
result_code TEXT
is_successful INTEGER
outcome success|failed|unknown
attempt_no INTEGER NOT NULL
created_at TEXT NOT NULL

UNIQUE(idempotency_key, attempt_no)
```

### `release_instructions`

```text
id TEXT PRIMARY KEY
funding_unit_id TEXT NOT NULL
provider_payment_id TEXT NOT NULL
operation_type TEXT NOT NULL DEFAULT 'approve_pool_payment'
idempotency_key TEXT NOT NULL UNIQUE
status created|submitted|confirmed|failed|unknown
created_at TEXT NOT NULL
updated_at TEXT NOT NULL

UNIQUE(funding_unit_id, operation_type)
```

## 13.2 Mock Moka provider DB

Ayrı DB:

```text
code/data/runtime/mock_moka.db
```

### `dealer_payments`

```text
dealer_payment_id INTEGER PRIMARY KEY AUTOINCREMENT
other_trx_code TEXT UNIQUE
virtual_pos_order_id TEXT UNIQUE
card_holder_full_name TEXT
card_number_first_six TEXT
card_number_last_four TEXT
amount_minor INTEGER NOT NULL
currency_code TEXT NOT NULL
installment_number INTEGER NOT NULL
is_pool_payment INTEGER NOT NULL
is_three_d INTEGER NOT NULL
description TEXT
software TEXT
payment_status INTEGER NOT NULL
trx_status INTEGER NOT NULL
ref_amount_minor INTEGER NOT NULL DEFAULT 0
approved_at TEXT
approval_undone_at TEXT
cancelled_at TEXT
statement_closed INTEGER NOT NULL DEFAULT 0
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

### `dealer_payment_transactions`

```text
dealer_payment_trx_id INTEGER PRIMARY KEY AUTOINCREMENT
dealer_payment_id INTEGER NOT NULL
trx_code TEXT UNIQUE
trx_type INTEGER NOT NULL
trx_status INTEGER NOT NULL
amount_minor INTEGER NOT NULL
payment_reason INTEGER NOT NULL
void_refund_reason INTEGER NOT NULL
virtual_pos_order_id TEXT
result_message TEXT
created_at TEXT NOT NULL
```

### `mock_operations`

Yalnız redacted request saklar.

Password, CheckKey full value ve CardToken persist edilmez.

---

# 14. Mock Moka HTTP server

## 14.1 Implement edilecek endpoint'ler

Demo minimum:

```text
POST /PaymentDealer/DoDirectPayment
POST /PaymentDealer/DoApprovePoolPayment
POST /PaymentDealer/UndoApprovePoolPayment
POST /PaymentDealer/GetDealerPaymentTrxDetailList
POST /PaymentDealer/GetPaymentList
```

Later:

```text
cancel
refund
marketplace
```

ayrı child plan olabilir.

## 14.2 HTTP behavior

Moka contract'a benzer şekilde:

- application errors HTTP 200 + ApiResponse error envelope dönebilir,
- malformed/non-JSON request için exact mock policy child plan'da dondurulur,
- M4Trust yalnız HTTP status'a bakmaz; ApiResponse parse eder.

## 14.3 Authentication behavior

Mock env:

```text
MOCK_MOKA_DEALER_CODE
MOCK_MOKA_USERNAME
MOCK_MOKA_PASSWORD
MOCK_MOKA_VIRTUAL_POS_ENABLED=true
```

Validation:

- missing/malformed → InvalidRequest
- wrong dealer/user/password/checkkey → InvalidAccount
- virtual pos disabled → VirtualPosNotFound

## 14.4 Demo payment tokenları

```text
DEMO-TOKEN-SUCCESS
DEMO-TOKEN-BANK-DECLINE
DEMO-TOKEN-TIMEOUT-AFTER-CREATE
```

Normal demo:

```text
DEMO-TOKEN-SUCCESS
```

Fault tokenlar yalnız test/dev mode'da.

## 14.5 Contract trace

Mock response header:

```text
X-Mock-Moka-Request-Id
```

ekleyebilir.

Bu Moka public contract parçası değildir; yalnız local debugging metadata'sıdır ve provider JSON'a eklenmez.

---

# 15. Error mapping

## 15.1 Domain error types

```text
ProviderAuthenticationError
ProviderValidationError
ProviderPaymentNotFound
ProviderPaymentAlreadyApproved
ProviderPaymentNotPool
ProviderOperationUnknown
ProviderTransportError
ProviderBankDecline
ProviderContractViolation
```

## 15.2 Mapping examples

```text
PaymentDealer.CheckPaymentDealerAuthentication.InvalidRequest
→ ProviderValidationError

PaymentDealer.CheckPaymentDealerAuthentication.InvalidAccount
→ ProviderAuthenticationError

PaymentDealer.DoApprovePoolPayment.DealerPaymentNotFound
→ ProviderPaymentNotFound

PaymentDealer.DoApprovePoolPayment.PaymentAlreadyApproved
→ reconciliation required

PaymentDealer.DoApprovePoolPayment.PaymentIsNotPoolPayment
→ ProviderPaymentNotPool

EX
→ ProviderOperationUnknown / provider incident
```

## 15.3 Fail closed

Unknown ResultCode:

```text
ProviderContractViolation
→ review case
→ no release completion
```

Mock yeni undocumented Moka code üretmez.

M4Trust internal error code ayrı tutulur.

---

# 16. Idempotency ve reconciliation

## 16.1 Create idempotency

Moka public contract'ta explicit idempotency-key field yoktur.

M4Trust:

- deterministic `OtherTrxCode`,
- internal unique constraint,
- operation state machine

ile idempotency sağlar.

## 16.2 Unknown create result

```text
HTTP timeout after request body sent
```

durumunda aynı create körlemesine tekrarlanmaz.

Akış:

```text
mark unknown
→ query detail by OtherTrxCode
→ found:
   bind provider payment
→ not found:
   controlled retry
```

## 16.3 Approve idempotency

Approve instruction unique'dir.

Timeout:

```text
approve_unknown
→ detail query
```

PaymentAlreadyApproved:

```text
detail query
→ approved ise success-equivalent reconcile
```

## 16.4 Reconciliation schedule

Demo:

- explicit button/API.

Production hardening:

- periodic job,
- unknown/failed states,
- stale pool states.

---

# 17. Milestone planına etkisi

## 17.1 Master plan override

Eski:

```text
milestone.released_amount_minor
single provider payment
multi partial approve
```

Moka profile için şu şekilde değişir:

```text
milestone
→ funding_units[]
→ each funding_unit one provider payment
→ each provider payment one full approval
```

Milestone aggregate:

```text
released_amount_minor =
sum(approved funding_unit.amount_minor)
```

## 17.2 Status

Milestone:

```text
pending
evidence_pending
eligible
held
funding_unit_approval_pending
partially_released
released
disputed
cancelled
```

`partially_released`:

```text
bazı funding unit'ler approved
bazıları bekliyor
```

anlamına gelir.

Provider payment'ın kendisi partial değildir.

## 17.3 Existing partial delivery regression

Legacy demo:

```text
delivered_quantity / contract_quantity
```

yerine contract-faithful demo fixture:

```text
fixed quantity tranches
```

kullanır.

Örnek:

```text
100 koli
4 x 25 koli tranche
```

50 koli e-irsaliye:

```text
U01 approve
U02 approve
U03 wait
U04 wait
```

Bu:

- yüzde 50 ödeme sonucunu korur,
- Moka public contract'a uygun şekilde iki ayrı pool approval yapar.

Scenario semantiği korunur; provider çağrı şekli değişir.

---

# 18. FundingCoordinator refactor

## 18.1 Yeni sorumluluk

`FundingCoordinator`:

- current package doğrular,
- funding plan yükler,
- pool payments ensure eder,
- unknown outcomes reconcile eder,
- transaction activation belirler.

Provider contract detayını router'a çıkarmaz.

## 18.2 Ratification router

Ratification tamamlanınca:

```python
funding_result = funding_coordinator.ensure_funded(...)
```

çağrılır.

Router:

- direct Moka call yapmaz,
- request envelope kurmaz,
- transaction state'i provider response'a göre kendi başına değiştirmez.

---

# 19. Settlement/ReleaseCoordinator refactor

## 19.1 Eski davranış kaldırılır

```python
approve_pool_payment(
    other_trx_code=transaction_id,
    capture_ratio=result.capture_ratio,
)
```

artık yoktur.

## 19.2 Yeni davranış

```text
evaluator
→ eligible funding unit IDs
→ release coordinator
→ one approve per unit
```

## 19.3 Decision output

Generic decision:

```text
capture_ratio
```

yerine integration boundary'de:

```text
eligible_funding_units[]
```

kullanılır.

Legacy compatibility adapter:

```text
capture_ratio
→ tranche threshold selection
```

yapabilir.

---

# 20. Demo API Trace özelliği

Jüri için yüksek değerli dikey özellik:

```text
Moka API Trace
```

Authorized manager görünümü:

```text
Endpoint
Timestamp
Operation
OtherTrxCode
VirtualPosOrderId
Amount
Currency
Redacted request JSON
Exact response JSON
ResultCode
Data.IsSuccessful
Mapped M4Trust status
```

Gösterim:

- gerçek localhost HTTP request/response,
- mock badge,
- “Moka public contract simulation” açıklaması.

Gösterilmeyen:

- password,
- raw CheckKey,
- CardToken,
- full IP,
- raw buyer PII.

Evidence bundle:

- full secret-free trace summary,
- request fingerprint,
- response hash,
- provider identifiers.

---

# 21. Configuration

```text
PAYMENT_PROVIDER=fake|moka_http

MOKA_CONTRACT_PROFILE=moka_payment_dealer_pool_v1
MOKA_BASE_URL=http://127.0.0.1:8001
MOKA_DEALER_CODE=DEMO-DEALER
MOKA_USERNAME=demo-user
MOKA_PASSWORD=demo-password
MOKA_CARD_TOKEN=DEMO-TOKEN-SUCCESS
MOKA_SOFTWARE=M4Trust
MOKA_TIMEOUT_SECONDS=20

MOCK_MOKA_DB_PATH=code/data/runtime/mock_moka.db
MOCK_MOKA_VIRTUAL_POS_ENABLED=true
MOCK_MOKA_FAULTS_ENABLED=false
```

`Settings.__repr__`:

- password,
- token,
- checkkey

maskeler.

---

# 22. Test planı

## 22.1 Contract DTO tests

Exact casing:

```text
PaymentDealerAuthentication
PaymentDealerRequest
DealerCode
CheckKey
IsPoolPayment
OtherTrxCode
VirtualPosOrderId
ResultCode
ResultMessage
Exception
IsSuccessful
```

Extra/missing field policy dondurulur.

## 22.2 CheckKey tests

- known fixture,
- wrong password,
- wrong order,
- Unicode/encoding,
- lowercase SHA-256 hex.

## 22.3 Serializer tests

- TRY → TL,
- 250000 minor → 2500.00 numeric,
- no binary float drift,
- exact JSON snapshot.

## 22.4 Direct payment tests

- success pool,
- IsPoolPayment=0 creates non-pool,
- invalid auth,
- virtual pos missing,
- bank decline,
- malformed request,
- unique OtherTrxCode.

## 22.5 Approve tests

- by VirtualPosOrderId,
- by OtherTrxCode,
- neither identifier,
- not found,
- already approved,
- non-pool payment,
- response envelope exact.

## 22.6 Undo tests

- approved pool success,
- not approved,
- not pool,
- mismatched IDs,
- statement closed behavior,
- exact public error codes where documented.

## 22.7 Detail query tests

- by OtherTrxCode,
- pending status 0/0,
- approved 2/1,
- transaction list present,
- unknown payment.

## 22.8 M4Trust client against mock server

`httpx.ASGITransport` veya live local server:

```text
create
→ parse
→ save IDs
→ approve
→ detail reconcile
```

## 22.9 Funding unit tests

- all-or-nothing one unit,
- fixed 4 tranches,
- exact amount sum,
- unique OtherTrxCode,
- package change changes codes,
- unsupported arbitrary proportional plan rejected.

## 22.10 Multi-release E2E

```text
4 funding units created
first evidence threshold
→ U01 approve

second threshold
→ U02 approve

U01 not called twice
U03/U04 pending
```

## 22.11 Unknown outcome tests

- timeout after mock persisted create,
- reconciliation binds payment,
- no duplicate create.
- timeout after approve,
- detail shows approved,
- instruction confirmed.

## 22.12 Secret leakage tests

- no password,
- no raw CheckKey,
- no raw CardToken,
- no PAN/CVC,
- no token in events/evidence/audit/log.

## 22.13 Regression

- approval-only one unit full release,
- document-only,
- fixed-tranche partial delivery,
- video anomaly hold before relevant unit approve,
- dispute blocks approve,
- dual ratification required,
- policy/package version integrity.

---

# 23. Implementation waves

## Wave M0 — Contract freeze

### Berke

- PaymentGateway port refactor draft,
- provider capability profile,
- funding-unit domain,
- current payment code impact map.

### Yusuf

- Moka public DTO models,
- golden JSON fixtures,
- error-code catalog,
- contract test skeleton.

### Freeze

- exact field casing,
- supported endpoints,
- standard profile scope,
- one unit / one payment / one approve rule.

## Wave M1 — HTTP client and mock server in parallel

### Berke branch

```text
feat/moka-http-client
```

- CheckKey,
- serializer,
- HTTP client,
- parser,
- mapper,
- redaction,
- fake gateway compatibility.

### Yusuf branch

```text
feat/moka-contract-mock-server
```

- separate FastAPI app,
- mock DB,
- direct payment,
- approve,
- undo,
- detail/list,
- public error codes.

### Shared ownership rule

`contracts.py` M0'dan sonra frozen.

Breaking DTO change iki taraf onayı ister.

## Wave M2 — Funding plan and persistence

### Berke

```text
feat/funding-units-provider-payments
```

- migrations,
- repositories,
- FundingCoordinator,
- OtherTrxCode.

### Yusuf

```text
feat/moka-contract-integration-tests
```

- client/server E2E,
- failure matrix,
- trace fixtures,
- secret leakage.

## Wave M3 — Milestone/settlement integration

### Berke

- `settlement.py`,
- release coordinator,
- funding-unit selection,
- provider state aggregate.

### Yusuf

- fixed-tranche compiler/evaluator,
- legacy partial regression adaptation,
- table-driven domain tests.

Hot file:

```text
settlement.py only Berke
```

## Wave M4 — Demo trace and docs

### Berke

- manager API trace endpoint,
- evidence trace summary,
- config/env/docs.

### Yusuf

- frontend trace panel,
- demo scenario,
- screenshots/demo script.

---

# 24. Existing master plan sections superseded

Bu plan aşağıdaki v2 kararlarını Moka profile için değiştirir:

## Superseded

```text
Provider approve_pool_payment(capture_ratio)
single mock payment released_amount/remaining_amount
same provider payment multiple release
arbitrary proportional provider release
Mock Ledger v2 as in-process-only ledger
transaction_id alone as OtherTrxCode
```

## Replacement

```text
one funding unit = one pool payment
one pool payment = one full approve
fixed tranches for partial delivery
separate local HTTP mock Moka server
real Moka HTTP client used in demo
deterministic per-unit OtherTrxCode
Moka ApiResponse exact envelope
reconciliation by OtherTrxCode
```

## Unchanged

- identity,
- legal entity,
- invitation,
- rule versioning,
- ratification,
- review,
- evidence,
- human-only dispute,
- decision purity,
- settlement single guard,
- adapter boundary,
- no raw card data,
- audit/provenance.

---

# 25. Acceptance criteria

Plan tamamlandığında:

1. Main backend ayrı local mock server'a gerçek HTTP POST atar.
2. Endpoint path'leri Moka public contract ile aynıdır.
3. Request top-level/block names exact casing kullanır.
4. Mock ApiResponse zarfı public contract şeklindedir.
5. Pool create `IsPoolPayment=1` kullanır.
6. Create response `VirtualPosOrderId` üretir ve saklanır.
7. Approve request yalnız identifier taşır; amount/capture ratio taşımaz.
8. Aynı pool payment ikinci kez approve edilince documented `PaymentAlreadyApproved` döner.
9. Pool olmayan ödeme approve edilince documented `PaymentIsNotPoolPayment` döner.
10. Unknown create/approve sonuçları reconciliation ile çözülür.
11. Her funding unit unique OtherTrxCode taşır.
12. Bir milestone fixed tranches ile birden fazla funding unit üretebilir.
13. 50% partial delivery demo'su iki ayrı pool payment approve ederek çalışır.
14. Tüm funding unit'ler ratification sonrası pool'da oluşturulmadan transaction active olmaz.
15. Password, CheckKey, CardToken, PAN ve CVC log/event/evidence'a girmez.
16. Manager UI redacted real request/response trace gösterebilir.
17. `PAYMENT_PROVIDER=moka_http` ile yalnız base URL değiştirerek local mock ve Moka sandbox aynı client kodunu kullanır.
18. Sandbox doğrulaması yapılmadıysa sistem bunu açıkça contract-faithful mock olarak etiketler.
19. Standard ve marketplace contract birbirine karıştırılmaz.
20. Full regression suite ve yeni contract tests yeşildir.

---

# 26. Demo anlatısı

Jüriye doğru ifade:

> M4Trust ödeme katmanı Moka United'ın kamuya açık Pool Payment contract'ına göre modellendi. Demo sırasında backend, in-process sahte fonksiyon çağırmak yerine ayrı çalışan yerel bir Moka simulator servisine gerçek HTTP JSON istekleri gönderiyor. Endpoint adları, authentication zarfı, `IsPoolPayment`, `OtherTrxCode`, `VirtualPosOrderId`, başarı cevapları ve temel hata kodları Moka'nın yayımlanmış contract'ıyla aynı. Gerçek Moka test hesabı sağlandığında aynı client'ın yalnız base URL ve credentials ayarları değiştirilerek sandbox'a yönlendirilmesi hedefleniyor.

Kaçınılacak iddia:

```text
Moka production entegrasyonu tamamlandı.
```

Doğru iddia:

```text
Public Moka contract-faithful HTTP mock ve production-oriented adapter hazır.
```

---

# 27. Kaynak referansları

Public doküman referansları:

```text
https://developer.mokaunited.com/index.php
https://developer.mokaunited.com/home.php?page=3dsiz-odeme
https://developer.mokaunited.com/home.php?page=havuzonay
https://developer.mokaunited.com/home.php?page=havuzonayiptal
https://developer.mokaunited.com/home.php?page=odeme-detay-listesi
https://developer.mokaunited.com/home.php?page=odeme-listesi
```

Optional marketplace profile referansları:

```text
https://developer.mokaunited.com/home.php?page=MP-3dsiz-odeme
https://developer.mokaunited.com/home.php?page=MP-havuzonay
```

Contract snapshot metadata:

```text
profile: moka_payment_dealer_pool_v1
retrieved_at: 2026-07-10
source: public developer portal
verification_status: mock-only until sandbox credentials available
```
