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

1. **Tam teslim:** kurallar çıkar ("%40 sevkiyat kanıtında, %60 depo tesliminde") → çift onay → e-irsaliye + video uyumlu → `capture`.
2. **Kısmi teslim:** kanıt sayımı sözleşme miktarının altında → `partial_capture`.
3. **Çelişkili kanıt:** e-irsaliye ↔ video çelişir → `dispute` + evidence snapshot; ödeme kilitli.
4. **Altın an — bozuk sözleşme:** milestone yüzdeleri 100 etmeyen sözleşme → validator **REJECT** + gerekçe. "LLM önerir, validator karar verir" iddiasının canlı kanıtı.

Her senaryonun sonunda evidence bundle indirilip gösterilir. Dashboard liste+detay modeli sayesinde üç senaryo önceden yüklenip aralarında gezilebilir.

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
