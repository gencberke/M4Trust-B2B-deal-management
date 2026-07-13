<!-- [[m4trust-fake-profile: delivery]] -->

# MAL ALIM SÖZLEŞMESİ (Teslimat-odaklı demo)

Bu sözleşme, M4Trust demo/manuel test amaçlıdır. Yukarıdaki
`[[m4trust-fake-profile: delivery]]` marker'ı, `LLM_PROVIDER=fake` iken
`FakeExtractionService`'in **teslimat profili** fixture'ını (iki e-irsaliye tranşı)
seçmesini sağlar; env `LLM_FAKE_PROFILE`'ı override eder. Marker PII olmadığından
maskeleme sonrası da korunur (bkz. `services/extraction.py`).

## Taraflar

- **Alıcı:** Örnek Alıcı A.Ş.
- **Satıcı:** Örnek Satıcı Ltd. Şti.

## Ticari Şartlar

- Konu: Endüstriyel Pompa — 10 adet
- Toplam tutar: 100.000 TRY
- Teslim tarihi: 2026-09-01

## Ödeme Kuralları

1. **İlk teslimat partisi:** İlk teslimatın e-irsaliyesi kesildiğinde tutarın
   **%50'si** ödenir. (tetik: e-irsaliye · kanıt: e-irsaliye)
2. **İkinci teslimat partisi:** Kalan teslimatın e-irsaliyesi kesildiğinde kalan
   **%50** ödenir. (tetik: e-irsaliye · kanıt: e-irsaliye)

> Bu iki tranş, funding schedule'da iki ayrı funding unit üretir; tracking policy
> e-irsaliye şartı nedeniyle doğal olarak açılır.
