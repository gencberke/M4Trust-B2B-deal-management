# AGENTS.md — M4Trust

Bu repo, **M4Trust** projesidir: Moka United Fintech Hackathon için geliştirilen, AI destekli bir B2B **şartlı ödeme / güven katmanı**. Sözleşme okunur → kurallar çıkarılır → deterministik validator denetler → iki taraf onaylar → teslimat kanıtına göre mock ödeme kararı üretilir.

## Önce bunu oku

Proje hakkında bağlamın yoksa, herhangi bir işe başlamadan önce şu sırayla oku:

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — bağlayıcı teknik referans: genel mimari, model/servis iletişimi (adapter'lar), API contract'ları, tech stack ve dışına çıkılmayacak tasarım kalıpları. **Koda dokunan her iş bu dokümana uymak zorundadır.**
2. **[plans/](plans/)** — planlama dokümanları (bkz. [plans/README.md](plans/README.md)): durum = klasör — `planning/` üzerinde çalışılan taslaklar, `ready/` uygulanmaya hazır planlar, `done/` uygulaması tamamlanmış planlar. Üzerinde çalıştığın işle ilgili olanı oku: [hackathon yol haritası](YOL_HARITASI.md), [Moka havuz/cüzdan entegrasyonu](plans/planning/moka_cüzdan_entegrasyonu.md), [regülasyon RAG genişletmesi](plans/planning/regulasyon_rag_genisletmesi.md).
3. **[report/](report/)** — sözel bağlam PDF'leri: [ana yapı ve kararlar](report/M4Trust_Ana_Yapi_ve_Kararlar_Guncel.pdf) (gerekçeler, jüri savunmaları), [kısa proje raporu](report/M4Trust_Kisa_Proje_Raporu_Guncel.pdf) (fikir anlatımı).

Akış diyagramları `diagram/` klasöründedir.

## Repo düzeni

```
ARCHITECTURE.md   bağlayıcı teknik referans  ← ÖNCE BUNU OKU
YOL_HARITASI.md   hackathon geliştirme yol haritası (sürekli referans)
plans/planning/   üzerinde çalışılan taslaklar (öneri tonunda, bağlayıcı değil)
plans/ready/      uygulanmaya hazır planlar — uygulama /plan-uygula komutuyla
plans/done/       uygulaması tamamlanmış planlar (tarihçe + sapma kaydı)
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

Plan durumu klasörle ifade edilir: `plans/planning/` (taslak) → `plans/ready/` (uygulanmaya hazır) → `plans/done/` (uygulandı). Bir planın uygulanması tercihen `/plan-uygula <plan-dosyası>` komutuyla yapılır; komut kullanılmasa bile **koda dokunan her iş için** şu protokol geçerlidir:

1. **Önce çelişki kontrolü:** Yapacağın iş ARCHITECTURE.md ile çelişiyor mu? §6'daki değişmez kalıplardan birini deliyorsa durup kullanıcıya sor. Mimaride henüz tanımlı olmayan bir yenilik (endpoint, servis, bağımlılık, event, şema alanı) getiriyorsa not al.
2. **Sonra doc-sync (işin parçası, atlanamaz):** Değişikliğin eskittiği dokümanı güncelle — endpoint → ARCHITECTURE §4.1 · extraction şeması → §4.2 (mutabakat şart) · event → §4.3 · servis/modül → §1 dizin · bağımlılık → §2 stack · tablo/state → §5 · yeni değişmez kural → §6 + buradaki özet · korpus/pratik gerçekler → buradaki "Pratik notlar". Güncelleme gerekmiyorsa raporunda "doc-sync: değişiklik gerekmedi" de.
3. **Plan durum bloğu:** Uyguladığın planın en üstüne `> **Durum:** Uygulandı — YYYY-AA-GG · Sapmalar: …` işle ve dosyayı `plans/done/` altına taşı.

Dokümantasyonu eskiten bir iş, doc-sync yapılmadan "bitti" sayılmaz.

## Pratik notlar

- Chroma index: `code/data/processed/embeddings/chroma/` — iki embed'li koleksiyon: `legal_articles` (891 vektör: TBK, 6493, 5549, KVKK, Yönetmelik, Tebliğ) ve `contract_examples` (395 vektör, 31 örnek sözleşme, few-shot yapısal referans). Üçüncü koleksiyon **`security_controls`** (PCI DSS kontrol haritası) için chunk'lar hazır (`data/processed/chunks/security/pci_dss_control_map.json`, 6 kontrol + 1 intro) ama **henüz embed edilmedi** (ağır RAG deps yoktu; `build_rag.py` çalıştırıldığında oluşur). Sorgular da BGE-M3 ile encode edilmelidir.
- İki TCMB metni (Yönetmelik + Tebliğ) `code/data/raw/legal/` altına eklendi, chunk'landı ve embed edildi — bkz. [plans/ready/regulasyon_rag_genisletmesi.md](plans/planning/regulasyon_rag_genisletmesi.md).
- `code/scripts/convert_documents.py` dolduruldu (`code/scripts/document_parser/`: PyMuPDF/python-docx/Tesseract, Clean Architecture, testli). İş sıralaması için [YOL_HARITASI.md](YOL_HARITASI.md).
- **AI extraction hattı uygulandı** (2026-07-08, [plans/done/ai_extraction_hatti.md](plans/done/ai_extraction_hatti.md)): `code/backend/app/` altında `config.py`, `schemas/extraction.py` (§4.2 donmuş Pydantic ikili sözleşme), `services/rag.py` (BGE-M3+Chroma, lazy), `services/privacy.py` (minimal PII mask/restore, §6.7), `services/extraction.py` (Fake + canlı OpenAI-uyumlu). `scripts/extract_contract.py` artık dolu (CLI: convert→mask→retrieve→extract→restore). LLM `gpt-5.4-mini`, `LLM_PROVIDER=fake|openai` (default `fake`); canlı çağrı için `code/backend/.env.example`'ı `code/.env`'e kopyalayıp `LLM_*` doldur.
- **RAG ContextBuilder + kart-verisi guardrail uygulandı** (2026-07-09, [plans/done/rag_context_builder_ve_guvenlik_katmani.md](plans/done/rag_context_builder_ve_guvenlik_katmani.md)): `services/context_builder.py` (çoklu-query/çoklu-koleksiyon orkestrasyon → `ContextPack`, §3.2); `ExtractionService.extract()` imzası `context: ContextPack | None`'a geçti (§3.1); `services/privacy.py`'ye `analyze()/PrivacyReport` (PAN+Luhn/CVV/track/PIN, kart placeholder'ı restore edilmez, SAD → blocking, §3.5); `config.security_collection`; `build_rag.py` `security/` → `security_controls` dalı; `scripts/extract_contract.py` CLI: convert→**analyze**→ContextBuilder→extract→restore + blocking'de canlı LLM atlanır + "dayanaklar" özeti (stderr). `--collection` **deprecated** (verilirse tek-koleksiyon debug bypass). §4.2 şeması **değişmedi**.
- **Env:** `code/.venv` (Python 3.12) — testler `cd code && ./.venv/bin/python -m pytest`. Minimal test bağımlılıkları kurulu (pydantic, openai, parser). **Canlı RAG için** `pip install -r requirements.txt` gerekir (chromadb + FlagEmbedding/torch, ~GB'lar); kurulu değilse CLI hattı RAG'ı atlayıp bağlamsız devam eder (graceful degradation).
- Ekip: Berke (backend + frontend), Yusuf (AI). Toplam süre 5-6 gün — kapsam eklerken bunu hesaba kat.
