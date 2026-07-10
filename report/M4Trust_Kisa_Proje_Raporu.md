

# M4Trust

## M4Trust Kısa Proje Raporu

AI destekli B2B güven ve şartlı ödeme katmanı

Hazırlık amacı: Moka United hackathon proje anlatımı

Okuyucu: Teknik detaya girmeden fikri anlamak isteyen jüri, mentor veya ekip dışı kişi

Sürüm: 08.07.2026 güncel

## Kısa Özet

M4Trust, şirketler arası ticarete sık yaşanan “önce mal mı gelsin, önce para mı gitsin?” güvensizliğini azaltmak için tasarlanmış AI destekli bir güven katmanıdır. Sistem, tarafların yüklediği sözleşmeyi okuyup ödeme ve teslimat şartlarını sade bir kurallar özetine dönüştürür. Taraflar bu özeti onayladıktan sonra ödeme akışı artık yapay zekanın serbest yorumuna değil, onaylanmış ve denetlenebilir kurallara göre ilerler.

Ana fikir: M4Trust yapay zekanın doğrudan para gönderdiği bir sistem değildir; sözleşme, mevzuat, teslimat kanıtı, video doğrulama sinyali ve taraf onayını birleştirerek B2B ödemeleri daha güvenli ve izlenebilir hale getiren bir katmandır.

## Çözdüğü Problem

KOBİ'ler ve ilk kez ticaret yapan şirketler için güven problemi çok nettir: satıcı, malı gönderdikten sonra parasını alamamaktan; alıcı ise parayı gönderdikten sonra ürünün gelmemesinden veya eksik gelmesinden çekinir. Banka akreditifi, factoring ve ticari sigorta gibi çözümler her şirket için erişilebilir, hızlı veya ekonomik değildir. Bu yüzden birçok işlem manuel takip, e-posta, dekont ve karşılıklı güven üzerine ilerler.

## Nasıl Çalışır?

1. Taraflar PDF, DOCX veya görsel formatındaki sözleşmeyi sisteme yükler.
2. Doküman ayrıştırma ve gerekli olduğunda OCR katmanı sözleşmeyi modele girecek sade bir markdown metnine dönüştürür.
3. RAG sistemi, sözleşme maddeleriyle ilgili mevzuat ve kaynak parçalarını bulup modele bağlam olarak sunar.
4. LLM/NLP katmanı ödeme, teslimat, taraf, tutar ve risk bilgilerini yapılandırılmış kural taslağına çevirir.
5. Validator katmanı yüzdeler, tarihler, taraflar, zorunlu alanlar ve onay sırası gibi deterministik kontrolleri yapar.
6. Sistem iki tarafa sade bir “kural özeti” gösterir; taraflar onaylamadan ödeme akışı aktif olmaz.
7. Teslimat kanıtı geldiğinde e-irsaliye ve video analizi birlikte değerlendirilir; karar motoru ödemeyi bırakır, tutar, kısmi bırakır veya dispute açar.

## Yapay Zekanın Rolü

Yapay zeka sistemde üç ana noktada kullanılır: sözleşme metnini anlamak, mevzuat ve kaynaklarla desteklenen bağlamı kullanmak, kararın gerekçesini okunabilir hale getirmek. Buna karşılık son ödeme davranışı yapay zekanın tek başına verdiği bir karara bırakılmaz. LLM önerir, insanlar onaylar, deterministik karar motoru uygular.

| Bileşen         | Görevi                                                                               |
|-----------------|--------------------------------------------------------------------------------------|
| OCR / Parser    | PDF, DOCX veya görsel sözleşmeyi markdown metnine çevirir.                           |
| RAG             | Kanun, uyumluluk ve sözleşme kaynaklarından ilgili parçaları getirir.                |
| LLM / NLP       | Kuralları, riskleri ve karar gerekçesini çıkarır.                                    |
| Validator       | Yüzdeler, tarihler, taraflar, zorunlu alanlar ve onay sırası gibi kontrolleri yapar. |
| Video Analizi   | Teslimat videosundan koli/palet sayımı ve hasar gibi risk sinyalleri üretir.         |
| Decision Engine | Onaylı kurala göre release, hold, partial release veya dispute sonucunu üretir.      |

## Moka United ile İlişki

Hackathon prototipinde gerçek para hareketi yapılmaz. Ödeme sağlayıcı katmanı Mock Moka Adapter ile simüle edilir. Üretim senaryosunda M4Trust, Moka United gibi lisanslı bir ödeme altyapısının üstünde çalışan kural, kanıt ve mutabakat katmanı olarak konumlanır. İki taraf onayına kadar paranın nasıl bekletileceği ve banka hesapları arası transferlerin production seviyede nasıl kurulacağı mentorlarla netleştirilecek konulardır.

## Demo Hikayesi

Jüri demosunda bir örnek sözleşme yüklenir. Sistem "%40 ödeme sevkiyat kanıtında, %60 ödeme depo tesliminde" gibi kuralları çıkarır ve taraf onayı ekranına getirir. Ardından e-irsaliye simüle edilir ve teslimat videosu üzerinden koli/palet sayımı gösterilir. Eksik teslimat veya çelişkili kanıt senaryosunda sistem tüm ödemeyi göndermek yerine kısmi ödeme veya dispute sonucuna geçer ve kanıt paketini oluşturur.

## Beklenen Etki

- KOBİ'ler için akreditif benzeri güveni daha erişilebilir hale getirir.
- Sözleşme ve ödeme takibini manuel süreçlerden çıkarır.
- Uyuşmazlıkları tamamen yok etme iddiası yerine, daha kanıtlı ve daha küçük hale getirmeyi hedefler.
- Tamamlanan işlemlerden gelecekte güven skoru ve ticari davranış analitiği üretme potansiyeli taşır.

## Tek Cümlelik Pitch

Pitch: M4Trust, KOBİ'ler için sözleşme, teslimat kanıtı, video doğrulama sinyali ve ödeme akışını birleştiren; AI destekli, Moka-ready bir B2B güven katmanıdır.