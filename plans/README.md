# plans/ — Plan Yaşam Döngüsü

Bu klasör projenin planlama dokümanlarını tutar. Bağlayıcı teknik çerçeve her zaman [ARCHITECTURE.md](../ARCHITECTURE.md)'dir; plan ile mimari çelişirse ya plan mimariye uyarlanır ya da ekip mutabakatıyla mimari güncellenir.

## Klasörler

- **v1/** — İlk, kesinleşmemiş öneriler. Ton: "bu plan neden ortaya çıktı, nasıl yaklaşabiliriz". Bağlayıcı değildir; araştırma ve tartışma zeminidir.
- **v2/** — Olgunlaşmış, uygulanmaya hazır planlar. Bir v1 planı ekipçe netleşince `v2_<ad>.md` adıyla buraya taşınır; kapsam, kabul kriterleri ve dokunacağı mimari bölümler netleştirilir.

## Uygulama akışı

1. Plan `v2/`'ye konur.
2. Ajana `/plan-uygula plans/v2/<dosya>.md` denir (komut yoksa plan dosyası işaret edilir; AGENTS.md'deki protokol her durumda geçerlidir).
3. Ajan sırasıyla: ARCHITECTURE.md ile çelişki kontrolü → implementasyon + doğrulama → **doc-sync** (ARCHITECTURE.md / AGENTS.md güncellenir) → plan durum bloğunu işler.

## Durum bloğu formatı

Her planın en üstünde tutulur ve uygulamayı yapan ajan tarafından güncellenir:

> **Durum:** Taslak | Olgunlaştı | Uygulanıyor | Uygulandı — YYYY-AA-GG · Sapmalar: …
