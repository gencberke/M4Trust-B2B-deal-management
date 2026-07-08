# AGENTS.md — M4Trust

Bu repo, **M4Trust** projesidir: Moka United Fintech Hackathon için geliştirilen, AI destekli bir B2B **şartlı ödeme / güven katmanı**. Sözleşme okunur → kurallar çıkarılır → deterministik validator denetler → iki taraf onaylar → teslimat kanıtına göre mock ödeme kararı üretilir.

## Önce bunu oku

Proje hakkında bağlamın yoksa, herhangi bir işe başlamadan önce şu sırayla oku:

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — bağlayıcı teknik referans: genel mimari, model/servis iletişimi (adapter'lar), API contract'ları, tech stack ve dışına çıkılmayacak tasarım kalıpları. **Koda dokunan her iş bu dokümana uymak zorundadır.**
2. **[plans/](plans/)** — planlama dokümanları (bkz. [plans/README.md](plans/README.md)): `v1/` öneri tonunda taslaklar, `v2/` olgunlaşmış ve uygulanmaya hazır planlar. Üzerinde çalıştığın işle ilgili olanı oku: [hackathon yol haritası](YOL_HARITASI.md), [Moka havuz/cüzdan entegrasyonu](plans/v1/v1_moka_cüzdan_entegrasyonu.md), [regülasyon RAG genişletmesi](plans/v1/v1_regulasyon_rag_genisletmesi.md).
3. **[report/](report/)** — sözel bağlam PDF'leri: [ana yapı ve kararlar](report/M4Trust_Ana_Yapi_ve_Kararlar_Guncel.pdf) (gerekçeler, jüri savunmaları), [kısa proje raporu](report/M4Trust_Kisa_Proje_Raporu_Guncel.pdf) (fikir anlatımı).

Akış diyagramları `diagram/` klasöründedir.

## Repo düzeni

```
ARCHITECTURE.md   bağlayıcı teknik referans  ← ÖNCE BUNU OKU
plans/v1/         plan taslakları (öneri tonunda, bağlayıcı değil)
plans/v2/         olgunlaşmış planlar — uygulama /plan-uygula komutuyla
report/           proje raporları (sözel bağlam, PDF)
diagram/          akış diyagramları (PNG)
code/scripts/     offline RAG hazırlığı (chunk + embed — çalışır durumda)
code/data/        mevzuat korpusu (Chroma index hazır) + 31 ham sözleşme PDF'i
code/backend/     FastAPI servisi (ARCHITECTURE §1'e göre kurulacak)
code/frontend/    React + Vite + Tailwind (ARCHITECTURE §1'e göre kurulacak)
```

## Değişmez ilkeler (tam liste: ARCHITECTURE.md §6)

- **LLM asla ödeme kararı vermez.** Zincir: LLM önerir → validator (deterministik) denetler → insanlar onaylar → motor uygular.
- **Gerçek para hareketi ve gerçek kart verisi yok.** Ödeme, Moka havuz ödeme contract'ına uygun mock provider ile simüle edilir.
- **Her dış bağımlılık adapter + fake çiftidir; dış LLM'e yalnızca maskelenmiş içerik gider.**
- **Extraction JSON şeması ikili sözleşmedir** (ARCHITECTURE §4.2): değiştirmeden önce ekipçe mutabakat gerekir.
- Dokümantasyon ve UI dili **Türkçe**dir.

## Plan yaşam döngüsü ve doc-sync protokolü

`plans/v1/` ilk önerileri, `plans/v2/` olgunlaşmış ve uygulanmaya hazır planları tutar. Bir planın uygulanması tercihen `/plan-uygula <plan-dosyası>` komutuyla yapılır; komut kullanılmasa bile **koda dokunan her iş için** şu protokol geçerlidir:

1. **Önce çelişki kontrolü:** Yapacağın iş ARCHITECTURE.md ile çelişiyor mu? §6'daki değişmez kalıplardan birini deliyorsa durup kullanıcıya sor. Mimaride henüz tanımlı olmayan bir yenilik (endpoint, servis, bağımlılık, event, şema alanı) getiriyorsa not al.
2. **Sonra doc-sync (işin parçası, atlanamaz):** Değişikliğin eskittiği dokümanı güncelle — endpoint → ARCHITECTURE §4.1 · extraction şeması → §4.2 (mutabakat şart) · event → §4.3 · servis/modül → §1 dizin · bağımlılık → §2 stack · tablo/state → §5 · yeni değişmez kural → §6 + buradaki özet · korpus/pratik gerçekler → buradaki "Pratik notlar". Güncelleme gerekmiyorsa raporunda "doc-sync: değişiklik gerekmedi" de.
3. **Plan durum bloğu:** Uyguladığın planın en üstüne `> **Durum:** Uygulandı — YYYY-AA-GG · Sapmalar: …` işle.

Dokümantasyonu eskiten bir iş, doc-sync yapılmadan "bitti" sayılmaz.

## Pratik notlar

- Chroma index: `code/data/processed/embeddings/chroma/` — koleksiyon `legal_articles`, 754 vektör, BGE-M3 ile embed'li. Sorgular da BGE-M3 ile encode edilmelidir.
- Korpusa eklenecek iki TCMB metni `code/data/raw/legal/` altında hazır bekliyor (henüz chunk/embed edilmedi) — bkz. [plans/regulasyon_rag_genisletmesi.md](plans/v1/v1_regulasyon_rag_genisletmesi.md).
- `code/scripts/convert_documents.py` ve `extract_contract.py` henüz boştur; iş sıralaması için [plans/v1/v1_hackathon_gelistirme_yol_haritasi.md](YOL_HARITASI.md).
- Ekip: Berke (backend + frontend), Yusuf (AI). Toplam süre 5-6 gün — kapsam eklerken bunu hesaba kat.
