# PCI DSS Kontrol Haritası — M4Trust

Bu doküman PCI DSS v4.0.1'in M4Trust akışına dokunan gereksinimlerinin kendi
cümlelerimizle yazılmış runtime karşılıklarıdır. Ham standart metni içermez.

## pci.req.3.sad_storage

source_ref: PCI DSS v4.0.1 Requirement 3
topic: sensitive_authentication_data
applies_when: girdi CVV/CVC, tam track data veya PIN/PIN blok içeriyorsa

runtime_rule: Hassas doğrulama verisi (SAD) yetkilendirme sonrasında saklanamaz;
dış LLM sağlayıcılarına gönderilemez ve kanıt paketlerinde tutulamaz.

m4trust_action: BLOCK_EXTERNAL_LLM · DO_NOT_RESTORE · NEEDS_REVIEW

## pci.req.3.pan_protection

source_ref: PCI DSS v4.0.1 Requirement 3
topic: pan_storage_masking
applies_when: girdi kart numarası (PAN) içeriyorsa

runtime_rule: PAN saklanacaksa okunamaz hale getirilmeli; görüntülenirken
maskelenmelidir (en fazla ilk 6 / son 4 hane). M4Trust PAN'ı dış LLM'e ham
göndermez ve çıktıya geri açmaz.

m4trust_action: MASK_PAN_BEFORE_LLM · DO_NOT_RESTORE · ADD_SECURITY_RISK_FLAG

## pci.req.4.transmission

source_ref: PCI DSS v4.0.1 Requirement 4
topic: cardholder_data_transmission

runtime_rule: Kart sahibi verisi açık/genel ağlar üzerinden güçlü kriptografik
koruma olmadan iletilemez. Kart verisi gerektiren akışlar lisanslı ödeme
sağlayıcısının (Moka) barındırdığı kanala yönlendirilir.

m4trust_action: REQUIRE_PROVIDER_HOSTED_FLOW · ADD_SECURITY_RISK_FLAG

## pci.req.7.access_restriction

source_ref: PCI DSS v4.0.1 Requirement 7
topic: need_to_know_access

runtime_rule: Kart sahibi verisine erişim iş gereksinimiyle sınırlıdır
(need-to-know). M4Trust maskeleme haritasını yalnızca lokalde tutar; evidence
bundle'a maskeli hal girer.

m4trust_action: LOCAL_ONLY_MAPPING · MASKED_EVIDENCE

## pci.req.10.logging_evidence

source_ref: PCI DSS v4.0.1 Requirement 10
topic: logging_and_evidence

runtime_rule: Log ve kanıt (evidence) çıktıları ham PAN, hassas doğrulama
verisi (SAD) veya maskelenmemiş hassas veri içermemelidir. M4Trust evidence
bundle'ına yalnızca maskeli içerik girer; maskeleme haritası lokalde kalır.

m4trust_action: MASKED_LOGS_ONLY · EVIDENCE_REDACTION_CHECK · ADD_SECURITY_RISK_FLAG

## pci.req.12.third_party

source_ref: PCI DSS v4.0.1 Requirement 12
topic: third_party_service_providers

runtime_rule: Kart verisine dokunan üçüncü taraf hizmet sağlayıcıların
sorumlulukları yazılı olarak tanımlanmalıdır. M4Trust anlatısında kart verisi
işleme tamamen lisanslı sağlayıcıda (Moka) kalır; M4Trust karar-kanıt katmanıdır.

m4trust_action: DELEGATE_TO_LICENSED_PROVIDER · ADD_SECURITY_RISK_FLAG
