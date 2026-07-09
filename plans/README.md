# plans/ — Plan Yaşam Döngüsü

Bu klasör projenin planlama dokümanlarını tutar; **planın durumu bulunduğu klasörle ifade edilir.** Bağlayıcı teknik çerçeve her zaman [ARCHITECTURE.md](../ARCHITECTURE.md)'dir; plan ile mimari çelişirse ya plan mimariye uyarlanır ya da ekip mutabakatıyla mimari güncellenir.

## Klasörler

- **planning/** — Üzerinde hâlâ çalışılan taslaklar. Öneri tonundadır ("neden ortaya çıktı, nasıl yaklaşabiliriz"), açık soruları/engelleri olabilir. Bağlayıcı değildir.
- **ready/** — Ekipçe netleşmiş, **uygulanmaya hazır** planlar: kapsam, iş kalemleri ve dokunacağı mimari bölümler bellidir, önlerinde engel yoktur.
- **done/** — **Uygulaması tamamlanmış** planlar. En üstlerindeki durum bloğu uygulama tarihini ve sapmaları taşır; tarihçe/kanıt olarak saklanır.

## Akış

1. Plan `planning/`'de olgunlaştırılır; netleşince `ready/`'ye taşınır.
2. Uygulama tercihen `/plan-uygula plans/ready/<dosya>.md` komutuyla yapılır (komutsuz da AGENTS.md'deki doc-sync protokolü geçerlidir).
3. Uygulamayı yapan ajan: ARCHITECTURE.md ile çelişki kontrolü → implementasyon + doğrulama → **doc-sync** (ARCHITECTURE.md / AGENTS.md güncellenir) → durum bloğunu işler ve dosyayı `done/`'a taşır.

## Durum bloğu formatı

> **Durum:** Uygulandı — YYYY-AA-GG · Sapmalar: … (yoksa "yok")

Not: [Hackathon yol haritası](../YOL_HARITASI.md) tek seferlik bir plan değil sürekli referans olduğu için proje kökünde yaşar.
