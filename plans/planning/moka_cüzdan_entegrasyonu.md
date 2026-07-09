# Plan: v1 Moka Cüzdan / Havuz Ödeme Entegrasyonu

> **Tür:** Öneri — karar verilmiş bağlayıcı tasarım değil. Bağlayıcı kısım (PaymentProvider interface'i) [ARCHITECTURE.md §3.3](../../ARCHITECTURE.md)'e işlendi.
> **Durum:** Mentor onayı bekleyen açık soru var (bkz. §5).

## 1. Bu plan neden ortaya çıktı?

Sistemimizin temel vaadi "iki taraf onaylamadan para transfer edilmez". Bunun canlıda çalışması için paranın taraflar arasında bir yerde **bekletilmesi** gerekiyor — biz lisanslı bir kuruluş olmadığımız için bu bekletmeyi kendimiz yapamayız. Soru Moka tarafına iletildi; mentor cevabı: *"iyzico korumalı havuz dediğin yapı bizim cüzdan yapısı ile aynı — parayı Moka United tarafından açılacak bir cüzdanda saklanacak gibi hayal edebiliriz."*

Bunun üzerine Moka United developer portal'ı araştırıldı. Sonuç: **bu bir engel değil** — Moka'nın public API'sinde "havuz ödeme" akışı zaten var ve bizim modele doğrudan oturuyor.

## 2. Araştırma özeti: Moka havuz ödeme contract'ı

Kaynak: [developer.mokaunited.com](https://developer.mokaunited.com/) · JSON + POST · test: `service.refmokaunited.com` · canlı: `service.mokaunited.com`

| İhtiyacımız | Moka karşılığı |
|---|---|
| Parayı havuza almak | Ödeme oluştururken `IsPoolPayment: 1` — para çekilir ama bayi onaylayana kadar havuzda bekler |
| Havuzu serbest bırakmak | `POST /PaymentDealer/DoApprovePoolPayment` (`VirtualPosOrderId` veya kendi `OtherTrxCode`'umuzla) |
| Onayı geri almak | `POST /PaymentDealer/UndoApprovePoolPayment` — ⚠️ yalnızca **gün sonundan / bayi ekstresi oluşmadan önce**; sınırsız rollback değil |
| Durum sorgulamak | Ödeme / Transaction / Detay listesi servisleri |
| Çok taraflı dağıtım (ileride) | Pazar Yeri Ödeme Servisleri (`SubDealer` listesi zorunlu) |

Başarılı cevap şekli: `ResultCode: "Success"` + `Data.IsSuccessful: true` + `Data.VirtualPosOrderId`.

Önemli tespit: Moka'da release **tek onay çağrısıdır**. "İki taraf onayladı mı?" mantığı Moka'ya taşınamaz — bu bizim iş kuralı katmanımızda kalır. Yani akış: alıcı öder (`IsPoolPayment=1`) → para havuzda → bizim backend çift onay + deterministik kural kararını toplar → koşullar sağlanınca **tek** `DoApprovePoolPayment` çağrısı → para serbest.

## 3. Önerilen yaklaşım

**Faz 0 — Hackathon (şimdi):** `PaymentProvider` adapter'ı yazılır; `MockMokaProvider` cevapları gerçek Moka response şekline birebir uyar (yukarıdaki alanlar), bizim `transaction_id` → `OtherTrxCode` eşlemesi kurulur. `PAYMENT_PROVIDER=mock`. Böylece frontend/backend gerçek contract'a göre gelişir ama para hareketi olmaz.

**Faz 1 — Sandbox:** Mentorlardan test ortamı erişimi alınırsa `RealMokaProvider` yazılır; yalnızca adapter altı değişir, akış aynı kalır.

**Karar noktası (v1'de):** normal havuz ödeme mi, pazar yeri modeli mi?
- *Basit yol:* normal havuz ödeme + bizim çift onay — demo için yeterli, önerimiz bu.
- *Pazar yeri yolu:* satıcıyı alt üye işyeri olarak modellemek — çok taraflı dağıtım için daha doğru ama entegrasyon karmaşıklığı artar. v1'de değerlendirilebilir.

## 4. Sınırlar ve dikkat noktaları

- `UndoApprovePoolPayment` gün sonu kısıtlıdır → jüri/mentor anlatısında "geri alma her zaman mümkün" **denmemeli**.
- **Cüzdan/wallet API contract'ı public dokümanda görünmüyor** (portal: ödeme alma, kart saklama, tekrarlayan ödeme, pazar yeri, havuz). Mentorun bahsettiği "cüzdan" muhtemelen private/kurumsal ürün — netleştirilmeden wallet varsayımıyla kod yazılmamalı; şimdilik havuz ödeme contract'ı baz alınmalı.
- Dispute durumunda havuzdaki paranın akıbeti (iade mi, bekletme mi, süre sınırı ne) dokümandan net değil — mentora sorulacaklar listesinde.

## 5. Mentorlara gönderilecek soru (hazır metin)

> Selamlar, Moka entegrasyonu tarafında doğru contract'a göre mock geliştirmek istiyoruz. Public developer portal'da havuz ödeme akışını gördük: ödeme oluştururken `IsPoolPayment: 1`, release için `/PaymentDealer/DoApprovePoolPayment`, geri alma için `/PaymentDealer/UndoApprovePoolPayment` kullanılıyor gibi duruyor.
>
> Bizim senaryoda iki taraf onayını kendi backend'imizde toplayıp, iki onay + deterministic rule engine kararı tamamlandığında Moka tarafındaki havuz ödemeyi tek bir release çağrısıyla onaylamayı planlıyoruz.
>
> Bu yaklaşım hackathon/prod senaryosu için doğru mu? Yoksa Moka United cüzdan/e-para tarafında kullanmamız gereken ayrı bir wallet API / sandbox contract var mı? Varsa ilgili endpoint dokümantasyonu veya örnek request-response paylaşabilir misiniz? Prod öncesinde gerçek para hareketi yapmadan, Moka response contract'ına uygun bir mock provider geliştireceğiz; hangi endpoint ve response formatını esas almamız gerektiğini netleştirmek istiyoruz.

## 6. Konumlandırma (jüri anlatısı)

Bu entegrasyon bir engel değil, güven hikayesinin kendisi: *"Parayı biz tutmuyoruz — lisanslı ödeme kuruluşunun havuz/cüzdan altyapısında bekliyor. Bizim sistemimiz yalnızca çift taraf onayı ve sözleşme kuralları tamamlandığında release talimatı üretiyor."*
