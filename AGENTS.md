# AGENTS.md — M4Trust

Bu repo, **M4Trust** projesidir: Moka United Fintech Hackathon için geliştirilen, AI destekli bir B2B **şartlı ödeme / güven katmanı**. Sözleşme okunur → kurallar çıkarılır → deterministik validator denetler → iki taraf onaylar → teslimat kanıtına göre mock ödeme kararı üretilir.

## Önce bunu oku

Proje hakkında bağlamın yoksa, herhangi bir işe başlamadan önce şu sırayla oku:

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — bağlayıcı teknik referans: genel mimari, model/servis iletişimi (adapter'lar), API contract'ları, tech stack ve dışına çıkılmayacak tasarım kalıpları. **Koda dokunan her iş bu dokümana uymak zorundadır.**
2. **[plans/](plans/)** — planlama dokümanları (bkz. [plans/README.md](plans/README.md)): durum = klasör — `planning/` üzerinde çalışılan taslaklar, `ready/` uygulanmaya hazır planlar, `done/` uygulaması tamamlanmış planlar. 
3. **[report/](report/)** — sözel bağlam PDF'leri: [ana yapı ve kararlar](report/ "md dosyaları") (gerekçeler, jüri savunmaları), [kısa proje raporu](report/ "md dosyaları") (fikir anlatımı).

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
code/backend/     FastAPI servisi (kuruldu: app + db + eventbus + router'lar + servisler)
code/frontend/    React + Vite + Tailwind (ARCHITECTURE §1'e göre kurulacak)
```

## Değişmez ilkeler (tam liste: ARCHITECTURE.md §6)

- **LLM asla ödeme kararı vermez.** Zincir: LLM önerir → validator (deterministik) denetler → insanlar onaylar → motor uygular.
- **Gerçek para hareketi ve gerçek kart verisi yok.** Ödeme, Moka havuz ödeme contract'ına uygun mock provider ile simüle edilir.
- **Her dış bağımlılık adapter + fake çiftidir; dış LLM'e yalnızca maskelenmiş içerik gider.**
- **Extraction JSON şeması ikili sözleşmedir** (ARCHITECTURE §4.2): değiştirmeden önce ekipçe mutabakat gerekir. Platformun operasyonel takip tercihi bu şemaya yazılmaz.
- **Video tek başına para hareketi üretemez.** Opsiyonel video advisory'dir: teslim miktarını, kısmi ödeme oranını, release'i veya dispute'u belirleyemez; en fazla `hold` + manuel inceleme tetikler.
- **Takip politikası taraf onaylarından önce kilitlenir**; sözleşmesel kanıt şartı (`required_evidence`) yönetici tercihiyle kapatılamaz.
- **Release guard tek yerdedir** (`services/settlement.py`); `decision.py` saf fonksiyon kalır, router'lar ödeme mantığının sahibi değildir.
- **Capability token'ları (buyer/seller/manager) log, event ve evidence'a girmez.**
- Dokümantasyon ve UI dili **Türkçe**dir.

## Plan yaşam döngüsü ve doc-sync protokolü

Plan durumu klasörle ifade edilir: `plans/planning/` (taslak) → `plans/ready/` (uygulanmaya hazır) → `plans/done/` (uygulandı). Bir planın uygulanması tercihen `/plan-uygula <plan-dosyası>` komutuyla yapılır; komut kullanılmasa bile **koda dokunan her iş için** şu protokol geçerlidir:

1. **Önce çelişki kontrolü:** Yapacağın iş ARCHITECTURE.md ile çelişiyor mu? §6'daki değişmez kalıplardan birini deliyorsa durup kullanıcıya sor. Mimaride henüz tanımlı olmayan bir yenilik (endpoint, servis, bağımlılık, event, şema alanı) getiriyorsa not al.
2. **Sonra doc-sync (işin parçası, atlanamaz):** Değişikliğin eskittiği dokümanı güncelle — endpoint → ARCHITECTURE §4.1 · extraction şeması → §4.2 (mutabakat şart) · event → §4.3 · servis/modül → §1 dizin · bağımlılık → §2 stack · tablo/state → §5 · yeni değişmez kural → §6 + buradaki özet · korpus/pratik gerçekler → buradaki "Pratik notlar". Güncelleme gerekmiyorsa raporunda "doc-sync: değişiklik gerekmedi" de.
3. **Plan durum bloğu:** Uyguladığın planın en üstüne `> **Durum:** Uygulandı — YYYY-AA-GG · Sapmalar: …` işle ve dosyayı `plans/done/` altına taşı.

Dokümantasyonu eskiten bir iş, doc-sync yapılmadan "bitti" sayılmaz.

## Pratik notlar

- Chroma index: `code/data/processed/embeddings/chroma/` — iki embed'li koleksiyon: `legal_articles` (891 vektör: TBK, 6493, 5549, KVKK, Yönetmelik, Tebliğ) ve `contract_examples` (395 vektör, 31 örnek sözleşme, few-shot yapısal referans). Üçüncü koleksiyon **`security_controls`** (PCI DSS kontrol haritası) için chunk'lar hazır (`data/processed/chunks/security/pci_dss_control_map.json`, 6 kontrol + 1 intro) ama **henüz embed edilmedi** (ağır RAG deps yoktu; `build_rag.py` çalıştırıldığında oluşur). Sorgular da BGE-M3 ile encode edilmelidir.
- İki TCMB metni (Yönetmelik + Tebliğ) `code/data/raw/legal/` altına eklendi, chunk'landı ve embed edildi — bkz. [plans/ready/regulasyon_rag_genisletmesi.md](plans/done/regulasyon_rag_genisletmesi.md).
- `code/scripts/convert_documents.py` dolduruldu (`code/scripts/document_parser/`: PyMuPDF/python-docx/Tesseract, Clean Architecture, testli). İş sıralaması için [YOL_HARITASI.md](YOL_HARITASI.md).
- **AI extraction hattı uygulandı** (2026-07-08, [plans/done/ai_extraction_hatti.md](plans/done/ai_extraction_hatti.md)): `code/backend/app/` altında `config.py`, `schemas/extraction.py` (§4.2 donmuş Pydantic ikili sözleşme), `services/rag.py` (BGE-M3+Chroma, lazy), `services/privacy.py` (minimal PII mask/restore, §6.7), `services/extraction.py` (Fake + canlı OpenAI-uyumlu). `scripts/extract_contract.py` artık dolu (CLI: convert→mask→retrieve→extract→restore). LLM `gpt-5.4-mini`, `LLM_PROVIDER=fake|openai` (default `fake`); canlı çağrı için `code/backend/.env.example`'ı `code/.env`'e kopyalayıp `LLM_*` doldur.
- **RAG ContextBuilder + kart-verisi guardrail uygulandı** (2026-07-09, [plans/done/rag_context_builder_ve_guvenlik_katmani.md](plans/done/rag_context_builder_ve_guvenlik_katmani.md)): `services/context_builder.py` (çoklu-query/çoklu-koleksiyon orkestrasyon → `ContextPack`, §3.2); `ExtractionService.extract()` imzası `context: ContextPack | None`'a geçti (§3.1); `services/privacy.py`'ye `analyze()/PrivacyReport` (PAN+Luhn/CVV/track/PIN, kart placeholder'ı restore edilmez, SAD → blocking, §3.5); `config.security_collection`; `build_rag.py` `security/` → `security_controls` dalı; `scripts/extract_contract.py` CLI: convert→**analyze**→ContextBuilder→extract→restore + blocking'de canlı LLM atlanır + "dayanaklar" özeti (stderr). `--collection` **deprecated** (verilirse tek-koleksiyon debug bypass). §4.2 şeması **değişmedi**.
- **Backend iskeleti + işlem akışı uygulandı** (2026-07-09, [plans/done/backend_iskeleti_ve_islem_akisi.md](plans/done/backend_iskeleti_ve_islem_akisi.md)): `code/backend/app/` altında `main.py` (app factory + startup `init_db` + `/health`), `db.py` (stdlib sqlite3, WAL, §5'teki 6 tablo, `connect/init_db/get_db`), `eventbus.py` (`emit` → events, §4.3). Servisler: `validator.py` (saf, 9 kontrol, REJECT>NEEDS_REVIEW>PASS), `decision.py` (saf, capture/partial/hold/dispute), `payment_provider.py` (`PaymentProvider` ABC + `MockMokaProvider`, gerçek Moka response şekli + `mock_payments` ledger), `video.py` (`VideoAnalyzer` ABC + `FakeVideoAnalyzer`, dosya-adı ipuçları `hasarli`/`eksik`), `evidence.py` (`build_bundle`, ham PII/kart/markdown içermez). Router'lar (§4.1'in 8 endpoint'i, ek yok): `transactions` (upload→arka plan pipeline: convert→analyze→ContextBuilder→extract→restore→validate; ham markdown yalnızca DB'de), `approvals` (token'lı idempotent çift onay → `create_pool_payment` → active), `delivery` (e-irsaliye + video → `decide` → §6.1 guard'ında release), `evidence`. §4.2 şeması **değişmedi**. **Çalıştırma:** `cd code && ./.venv/bin/uvicorn backend.app.main:app --reload` (→ `/docs`); tek worker + WAL (çoklu worker çalıştırılmaz). Runtime DB: `code/data/runtime/m4trust.db` (gitignore). Env ekleri: `PAYMENT_PROVIDER=mock`, `VIDEO_ANALYZER=fake`, `DB_PATH`, `VALIDATOR_CONFIDENCE_THRESHOLD=0.7`. **Sapma:** `document_parser` `code/scripts/` altında kaldı; backend onu `sys.path` köprüsüyle import eder (ARCHITECTURE §1 `services/documents/` öngörür — sonraki relokasyon işi).
- **Env:** `code/.venv` (Python 3.12) — testler `cd code && ./.venv/bin/python -m pytest` (149 test yeşil). Minimal + web bağımlılıkları kurulu (pydantic, openai, parser, fastapi/uvicorn/python-multipart/httpx). **Canlı RAG için** `pip install -r requirements.txt` gerekir (chromadb + FlagEmbedding/torch, ~GB'lar); kurulu değilse pipeline RAG'ı atlayıp bağlamsız devam eder (graceful degradation). API testleri `with TestClient(app) as c:` bağlam yöneticisiyle koşmalı (lifespan/`init_db` yalnızca öyle tetiklenir).
- **VideoAnalyzer uygulandı** (2026-07-09, ARCHITECTURE §3.4): `services/video/` — `FakeVideoAnalyzer` (ağa çıkmaz, sabit çıktı) + `RoboflowVideoAnalyzer` (iki hosted YOLOv8 modeli: koli/palet + hasar, düz `requests` REST — `inference-sdk` Python 3.13'ü henüz desteklemiyor). `VIDEO_PROVIDER=fake|roboflow` (default `fake`); canlı çağrı için `code/backend/.env.example`'daki `ROBOFLOW_API_KEY`'i `code/.env`'e doldur. 7 gerçek fotoğrafla doğrulandı: ayrık koli/palette güvenilir, istiflenmiş palette eksik sayıyor (bilinen sınır, §3.4'te detay). Birden fazla video/fotoğrafın toplanması (aynı teslimatın farklı çekimleri) henüz kapsam dışı — istismar riski nedeniyle üst katmanda ele alınmalı.
- **Env:** `code/.venv` (Python 3.12) — testler `cd code && ./.venv/bin/python -m pytest`. Minimal test bağımlılıkları kurulu (pydantic, openai, parser). **Canlı RAG için** `pip install -r requirements.txt` gerekir (chromadb + FlagEmbedding/torch, ~GB'lar); kurulu değilse CLI hattı RAG'ı atlayıp bağlamsız devam eder (graceful degradation). **Video için** `requests`/`opencv-python-headless` gerekir (requirements.txt'e eklendi).
- **Opsiyonel fiziksel teslimat + video takip politikası uygulandı** (2026-07-10, backend; [plans/done/opsiyonel_fiziksel_teslimat_ve_video_takip_politikasi.md](plans/done/opsiyonel_fiziksel_teslimat_ve_video_takip_politikasi.md)): fiziksel teslimat ve video artık varsayılan ödeme yolu değil, yöneticinin açtığı **takip politikası**dır. Yeni: `schemas/tracking.py`, `services/tracking_policy.py` (persistence + deterministik `recommend_physical_delivery`), `services/effective_requirements.py` (saf resolver: contractual/operational/advisory), `services/settlement.py` (tek release guard; approval, e-irsaliye ve video aynı yolu kullanır), `services/extraction_projection.py` (public cevaplarda `tax_id`/`source_quote` yok). DB: `tracking_policies` tablosu + `transactions.manager_token` (additive, idempotent migration; **eski runtime DB'ye backfill yok** — tazelemek için `code/data/runtime/m4trust.db` elle silinir). API: `manager_link` + `manager-view` + `PUT tracking-policy` + `tracking-policy/lock`; policy kilitlenmeden onay 409; `awaiting_review` onay bypass'ı **kapandı**. Kanal guard'ı: takip etkin değilse e-irsaliye/video 409, `decided` işlemde geç kanıt `TRANSACTION_DECIDED`. Semantik değişiklik: **opsiyonel video anomalisi artık `dispute_opened` üretmez**, `hold` + `manual_review_required` üretir; video sayımı `delivered_quantity` fallback'i değildir. Fake extraction fixture'ı approval-only'ye çekildi; `FakeVideoAnalyzer` ipuçları `eksik`/`hasarli`/`dusuk_guven`. Env eki: `VIDEO_ADVISORY_CONFIDENCE_THRESHOLD=0.80`. §4.2 şeması **değişmedi** (yapısal snapshot testi `tests/test_extraction_schema.py`de). **Frontend ayrı plandadır.**

