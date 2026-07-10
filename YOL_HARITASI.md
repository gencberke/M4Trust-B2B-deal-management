# Plan: Hackathon Geliştirme Yol Haritası

> **Tür:** Öneri — sıralama ve zamanlama esnektir; bağlayıcı teknik çerçeve [ARCHITECTURE.md](ARCHITECTURE.md)'dedir.
> **Kaynak:** 08.07.2026 tasarım oturumu (eski `report/M4Trust_Genel_Yapi_ve_Uygulama_Plani.md` içinden ayrıştırıldı).

## 1. Bu plan neden ortaya çıktı?

Süre 5-6 gün, ekip iki kişi (berke ve yusuf) ve hedef jüri önünde uçtan uca çalışan bir demo. Bu kısıtlar iki şeyi zorunlu kılıyor: **ikilinin birbirini beklemeden paralel çalışabilmesi** ve **demo gününe fallback'li gelinmesi**. Plan bu iki ihtiyaç etrafında kurgulandı.

Paralelliği sağlayan mekanizma mimaride hazır: AI servisleri interface arkasında (`Fake*` implementasyonlarla), tek senkronizasyon noktası extraction JSON şeması. **Şema 1. gün Pydantic modeli olarak sabitlenirse** iki hat bağımsız ilerler — bu planın en kritik varsayımı budur.

## 2. Önerilen sıralama

| Berke, Yusuf (backend + frontend + AI)                                                                                                                                 |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Backend iskeleti: DB şeması, eventbus, extraction Pydantic şeması (**sabitlenir**), upload + PyMuPDF extraction, fake extraction ile uçtan uca akış; frontend scaffold |
| Detector model araştırması (§4) + `extract_contract.py` CLI ile prompt denemeleri                                                                                      |
| Validator, taraf linkleri + onay akışı, privacy/maskeleme katmanı, review/approval ekranları                                                                           | 
| RAG retrieval fonksiyonu + LLM structured extraction → gerçek `ExtractionService`                                                                                      |
| Decision engine + PaymentProvider (mock) + e-irsaliye simülasyonu + evidence bundle; dashboard                                                                         | 
| Video pipeline: frame sampling + detector + dedup'lu sayım → `VideoAnalyzer`'a takma                                                                                   |
| Demo senaryolarının hazırlanması (§3), kırma testleri, UI cilası                                                                                                       | 
| Açık kaynak model benchmark notebook'u (BERTurk / Qwen / Llama) — ar-ge eki                                                                                            |
| Demo provası + ekran kaydı fallback                                                                                                                                    |

## 3. Demo senaryoları 

Her senaryoda yönetici, taraf onaylarından önce **takip politikasını** seçip kilitler (`off` · `document_only` · `document_and_video`). Video hiçbir senaryoda ödeme miktarını belirlemez; ikincil (advisory) risk sinyalidir.

1. **Hizmet / approval-only:** fiziksel teslimat yok, takip `off` → çift onay → harici teslimat kanıtı beklenmez → `capture`.
2. **Fiziksel mal / yalnız belge:** takip `document_only` → çift onay → e-irsaliye tam teslim → `capture`. Video alanı hiç görünmez.
3. **Kısmi teslim:** e-irsaliye sözleşme miktarının altında → `partial_capture` (oran **yalnız e-irsaliyeden**).
4. **Yardımcı video uyumlu:** takip `document_and_video` → video e-irsaliye ile uyumlu → destekleyici bulgu, oran değişmez → `capture`.
5. **Yardımcı video anomalisi:** yüksek güvenli sayım ayrışması veya eşleşmiş hasar sinyali → `hold` + **manuel inceleme**; ödeme bırakılmaz, otomatik `dispute` **açılmaz**.
6. **Sözleşmesel video:** sözleşme videoyu açıkça şart koşuyorsa yönetici bunu kapatamaz; video gelene kadar `hold`.
7. **Altın an — bozuk sözleşme:** milestone yüzdeleri 100 etmeyen sözleşme → validator **REJECT** + gerekçe. "LLM önerir, validator karar verir" iddiasının canlı kanıtı; policy/onay/ödeme akışı hiç başlamaz.

Her senaryonun sonunda evidence bundle (takip politikası snapshot'ı dahil) indirilip gösterilir. Dashboard liste+detay modeli sayesinde senaryolar önceden yüklenip aralarında gezilebilir.

> **Not (2026-07-10):** Eski "e-irsaliye ↔ video çelişkisi → otomatik `dispute`" demosu bilinçli olarak kaldırıldı — video modelinin tek başına dispute açması güvenli değildir. Yerine 5. senaryo (`hold` + manuel inceleme) geçti. Gerekçe: [plans/done/opsiyonel_fiziksel_teslimat_ve_video_takip_politikasi.md](plans/done/opsiyonel_fiziksel_teslimat_ve_video_takip_politikasi.md).

## 4. Video detector: model seçimi 

Karar "baştan gerçek detector" yönünde; ama **COCO-pretrained YOLO'da karton koli/palet sınıfı yok** — hazır YOLOv8n bu işi doğrudan yapamaz. Önerilen değerlendirme sırası:

1. **Roboflow Universe hazır modeli** ("cardboard box / package detection" eğitilmiş YOLOv8 ağırlıkları) — hafif ve hızlı, muhtemelen en pratik yol.
2. **Open-vocabulary detection** (YOLO-World / Grounding DINO, "cardboard box" text prompt) — eğitimsiz zero-shot; daha ağır ama video arka planda işlendiği için kabul edilebilir. Yedek yol.
3. Mini dataset ile fine-tune — bu sürede riskli, önerilmez.

`damaged_box` için hazır model bulmak zor; hasar sinyalini MVP'de sadeleştirmek (sayım + düşük confidence + manuel işaretleme) makul. Detector gecikirse `FakeVideoAnalyzer` akışı taşır — demo bloklanmaz.

## 5. Riskler ve fallback'ler

- **LLM API erişimi/kesintisi** → `FakeExtractionService` fixture'ları her zaman çalışır halde tutulur.
- **Detector hazır olmazsa** → fake analyzer + "gerçek pipeline şurada, model şu" anlatısı.
- **Demo canlı patlarsa** → 6. gün çekilecek ekran kaydı yedeği.
- **Chunker uyumu:** ~~mevzuat metinlerindeki `GEÇİCİ MADDE` mevcut regex'e yakalanmıyor~~ düzeltildi — regex artık `GEÇİCİ MADDE` ve `EK MADDE`'yi de ayrı madde olarak yakalıyor, önceki chunk'a yapışma sorunu yok.
