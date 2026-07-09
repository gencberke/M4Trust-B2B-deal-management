# Plan: Regülasyon RAG Genişletmesi ve Veri Güvenliği Katmanı

> **Tür:** Öneri + kısmen tamamlanmış iş listesi. Mimariye işlenen bağlayıcı kısımlar: `privacy.py` maskeleme katmanı ve "LLM'e giden içerik sınırlandırılır" ilkesi ([ARCHITECTURE.md §3.5](../../ARCHITECTURE.md)).
> **Kaynak:** Moka mentor dönütü (08.07.2026) + aynı gün yapılan doğrulamalı web araştırması.

## 1. Bu plan neden ortaya çıktı?

Moka mentorü, Ödeme Hizmetleri ve Elektronik Para Kuruluşu olarak tabi oldukları regülatif kaynakları ve veri tanımlarını paylaşıp ChromaDB'de olmayanların eklenmesini önerdi. Gerekçesi: temel akışı değiştirmese de **bilgi güvenliği ile veri işleme/saklama/paylaşma sınırlarını modele baştan dahil etmek**. Bizim tarafta verilen taahhüt: eksik kaynaklar RAG hattına ayrı bir veri güvenliği katmanı olarak eklenecek; sözleşme markdown'a çevrildikten sonra veri sınıflandırma + maskeleme + validator kontrolleriyle LLM API'ye giden içerik sınırlandırılacak.

## 2. Eksik analizi (mentor listesi ↔ korpus)

| Mentor kaynağı | Korpusta? | Not |
|---|---|---|
| 6493 sayılı Kanun | ✅ Var | Tam metin, 40 chunk |
| KVKK (6698) | ✅ Var | Tam kanun metni; "Kişisel Veri" (md.3/d) ve "Özel Nitelikli Kişisel Veri" (md.6) tanımları içinde |
| TCMB Tebliği (RG 31676) | 🔶 PDF indirildi | "Müşteri Bilgisi" (md.3/şş) ve "Hassas Müşteri Verisi" (md.3/z) tanımları **burada** |
| TCMB Yönetmeliği (RG 31676) | 🔶 PDF indirildi | ⚠️ Mentor tablosuna düzeltme: "Müşteri Bilgisi" tanımı Yönetmelik'te yok, yalnızca Tebliğ'de |
| PCI DSS | ❌ Ham metin eklenmeyecek | Lisans engeli — §4 |

## 3. Eklenecek iki mevzuat metni (doğrulanmış, lisans engeli yok)

**TCMB Tebliği — Bilgi Sistemleri ve Veri Paylaşım Servisleri (No 39081).** Son değişiklik 28/3/2025 (RG 32855). Konsolide PDF: <https://www.mevzuat.gov.tr/MevzuatMetin/yonetmelik/9.5.39081.pdf> → repo kopyası `code/data/raw/legal/teblig_39081_bilgi_sistemleri.pdf`. 34 madde, `**MADDE N**` yapısı (chunker uyumlu).
RAG önceliği: **md.3** (tanımlar) → **md.21** (veri lokalizasyonu: birincil/ikincil sistemler yurt içinde) → **md.9** (veri güvenliği/mahremiyeti, açık rıza şartı) → md.8 → md.12-13 (10 yıl saklama).

**TCMB Yönetmeliği — Ödeme Hizmetleri ve Elektronik Para İhracı (No 39080).** Son değişiklik **19/3/2026** (RG 33201 — çok taze; embed bu sürümden yapılmalı). Konsolide PDF: <https://www.mevzuat.gov.tr/MevzuatMetin/yonetmelik/7.5.39080.pdf> → repo kopyası `code/data/raw/legal/yonetmelik_39080_odeme_hizmetleri.pdf`. 86 madde (+4/A, 36/A).
RAG önceliği: **md.21** (dış hizmet alımı — yurt dışı LLM API kullanımı bu kapsamda; md.21(7): TCMB'nin denetim hakkını engelleyen yasal engel olmamalı) → **md.62** (hassas müşteri verisi yurt içinde saklanır; yurt dışı paylaşım talepsiz yasak) → md.3 → md.19.

## 4. PCI DSS: ham metin gömülmesin, kendi özetimizi yazalım

- Güncel sürüm **v4.0.1** (v3.2.1 ve v4.0 emekli; 2026'da tek geçerli sürüm). Resmî Türkçe çevirisi yok.
- PCI SSC Terms & Conditions ham metnin kullanımını kısıtlıyor (*"personal, non-commercial"*, *"no derivative works"*) → standardı ChromaDB'ye gömmek yazılı şart ihlali riski.
- **Öneri:** 12 requirement için ekip kendi cümleleriyle kısa özet/eşleme dokümanı yazar (requirement başına 2-3 cümle + numara atfı; kaynak: <https://www.pcisecuritystandards.org/document_library/>), korpusa o eklenir. Demo'da gerçek kart verisi zaten yok; PCI DSS bağlamı prod konumlandırma anlatısı içindir.

## 5. Nasıl yaklaşabiliriz — iş kalemleri

- [x] Resmî konsolide PDF'ler indirildi, içerikleri doğrulandı, `code/data/raw/legal/` altına kopyalandı (08.07.2026).
- [x] İki metni markdown'a çevir → chunk'la → `build_rag.py` ile embed et (08.07.2026). Not: dosya adları önerilen `teblig_39081_...`/`yonetmelik_39080_...` yerine mevcut 4 dosyayla aynı enformel isimlendirme kullanıldı (`tebliğ.pdf`, `Yönetmelik.pdf`) — işlevsel fark yok, zaten embed edilip doğrulandı.
- [ ] PCI DSS özet/eşleme dokümanını yaz → korpusa ekle. **Kapsam dışı bırakıldı (08.07.2026):** 400 sayfa + İngilizce, hackathon süresi için maliyeti faydasından yüksek görüldü.
- [ ] `services/privacy.py` maskeleme katmanı (regex+sözlük: TCKN/vergi no, IBAN, telefon, adres; maskeleme haritası lokalde kalır, evidence'a maskeli hal girer).
- [ ] Validator'a "hassas veri" kontrolü: extraction çıktısında maskelenmemiş hassas alan → NEEDS_REVIEW.

## 6. Yan kazanç: jüri/mentor anlatısı

Tebliğ md.21 (veri lokalizasyonu) + Yönetmelik md.21(7) ve md.62, **local-first mimarinin ve açık kaynak model benchmark planının regülatif gerekçesidir**: "Maskeleme + local model hattımız keyfî bir tercih değil; md.21/62'nin çizdiği sınırların mimari karşılığı. Benchmark metrikleri tutarsa prod'da veri yurt dışına hiç çıkmaz."
