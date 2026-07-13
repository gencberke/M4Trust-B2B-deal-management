> **Durum:** Uygulandı — 2026-07-13 · Sapmalar: P0–P2 ve F1–F3 önceki PR'larda tamamlandı; F4–F5 bu kapanış branch'inde uygulandı. Kullanıcı talebiyle otomatik test, lint, typecheck, build ve tam uçtan uca doğrulama çalıştırılmadı; yalnız kısa tarayıcı kırıklık kontrolü yapıldı.

# Plan 14 — Demo/test kolaylaştırma + kapsamlı UI redesign

## Bağlam

M4Trust "real-life oriented" kurgulandığı için tam yaşam döngüsünü (upload →
extraction → davet → profil onayı → policy lock → çift ratification → funding →
kanıt → release → settled) elle test etmek/göstermek çok zahmetli:

- Happy path ≈ **13 HTTP çağrısı × 2 ayrı authenticated oturum** (session cookie +
  CSRF + `X-Acting-Entity-ID`).
- Davet linki yalnız bir API cevabında görünür; token hash'li saklandığı için
  **sonradan kurtarılamaz** (fake notification provider linki ne loglar ne saklar).
- UI'da hiçbir stepper / "sıradaki adım" rehberliği yok; tek `StatusBadge` + tek
  açıklayıcı cümle (`overviewProjection.ts::stateNotice`). Koşullu butonlar
  görünmez, `awaiting_review` UI'da çıkmaz sokak.
- **Default fake extraction fixture'ı approval-only** (tek kural,
  `trigger=approval`) → tracking policy doğal olarak `off` → `evaluate_settlement`'a
  giden HTTP tetikleyicisi yok, demo `active`'de tıkanır.
- Senaryo seeder'ı yok: `scripts/seed_demo_users.py` yalnız kullanıcı/entity üretir.

Kararlar: (1) hem jüri demosu hem manuel test için dengeli çözüm; (2) demo araçları
env flag arkasında **gizli**, normal UI temiz; (3) **kapsamlı frontend redesign** —
görsel yön aşağıdaki referansa göre.

ARCHITECTURE §6 değişmezleri her fazda korunur: LLM para yolunda yok; release guard
yalnız `services/settlement.py`; demo uçları provider çağırmaz / state zorlamaz;
ExtractionJSON şeması donuk; video advisory; token/secret log-audit'e girmez.

## Görsel referans (kullanıcının verdiği JPG — bağlayıcı)

Açık zeminli, kurumsal fintech dashboard estetiği:

- **Font:** Urbanist (Google Fonts; self-host edilir — mevcut Inter yerine geçer).
- **Renkler:** primary indigo `#3e30d9` (aktif nav pill'i, birincil buton, grafik
  vurgusu); pozitif/başarı yeşili `#51b206` (artış metrikleri, tamamlanmış adımlar);
  zemin açık gri `#f1f3f7`; kartlar beyaz `#ffffff`.
- **Doku:** büyük radius'lu (rounded-2xl/3xl) beyaz kartlar, çok hafif gölge,
  bol beyaz alan; koyu metin (`slate-900` civarı), ikincil metin gri.
- **Nav:** üstte yatay menü — aktif öğe dolgulu indigo pill; solda ikon rail
  (bizde SectionNav bu dile çevrilir: aktif sekme indigo pill).
- **Kart deseni:** üstte ikon + etiket, altında büyük sayı, sağda yeşil delta —
  transaction list/overview stat kartlarında bu desen kullanılır.
- **Ima:** mevcut dark tema (`color-scheme: dark`, `#020617` zemin, cyan vurgu)
  tamamen terk edilir → tüm `bg-white/5`, `border-white/10`, `text-slate-100`
  utility'leri token-tabanlı açık temaya taşınır. Bu, F1'in maliyetini artıran
  bilinçli karardır.

## Tasarım kararları

### D1 — Senaryo aracı: service-level `demo_scenarios` modülü

- Yeni `code/backend/app/services/demo_scenarios.py`: transaction'ı YALNIZ gerçek
  servisleri çağırarak ilerletir (`transaction_pipeline.run_pipeline`,
  `ParticipantService`, `tracking_policy`, `RatificationPackageService`,
  `services/ratifications`, evidence servisi, `settlement.evaluate_settlement`).
  Ham SQL ile business state yazılmaz; guard'ı ihlal edecek adım gerçek 409'u
  yüzeye çıkarır (state zorlanmaz).
- İdempotent adımlar: `create_uploaded`, `attach_and_confirm_parties`,
  `lock_policy`, `build_package`, `ratify(role)`, `submit_eirsaliye(quantity)`;
  seed'li Berke/Yusuf kullanıcı/entity ID'leriyle "karşı taraf adına" çalışır.
- `code/scripts/seed_demo_scenarios.py` (CLI): önce `seed_demo_users.py`'ı çağırır,
  sonra senaryo matrisi üretir: `awaiting_ratification / active / active+kısmi
  teslimat / settled / disputed / awaiting_review` (awaiting_review = validator
  NEEDS_REVIEW üreten fixture; disputed = disputes servisiyle gerçek dispute).
  Deterministik sözleşme başlıklarıyla idempotent.
- Neden HTTP değil: server + 2 cookie oturumu + CSRF + login rate limit (5/300s)
  maliyeti; HTTP gerçekçiliğini ~1000 test zaten kapsıyor. Neden test SQL
  builder'ları değil (`tests/test_ratifications.py::_setup_open_package` vb.):
  servisleri bypass edip event/audit/funding-unit boşlukları bırakıyorlar; ayrıca
  aynı modül D3'teki demo router'a da lazım — tek implementasyon iki tüketici.

### D2 — Delivery-oriented fake extraction profili

- `services/extraction.py::FakeExtractionService.extract()` masked markdown içinde
  `[[m4trust-fake-profile: delivery]]` marker'ı arar (FakeVideoAnalyzer
  filename-hint deseninin aynısı); marker yoksa env `LLM_FAKE_PROFILE=approval|delivery`
  (yeni `Settings` alanı, default `approval` → mevcut davranış bit-bit korunur).
  `extract(masked_markdown, context)` imzası değişmez.
- Yeni `_fake_fixture_delivery()`: aynı taraflar; `payment_rules` = 2 tranş
  (`trigger="e_invoice"`, %50 + %50, `required_evidence=["e_irsaliye"]`, miktarlı
  mal) → funding schedule 2 unit üretir, tracking policy doğal olarak açılır,
  e-irsaliye → milestone evaluator → settlement zinciri gösterilebilir olur.
- **ExtractionJSON şeması DEĞİŞMEZ** — `tests/test_extraction_schema.py`
  snapshot'ı kanıttır.
- Marker'lı demo sözleşme dosyaları `code/data/demo/` altına.

### D3 — Gizli demo araçları: `DEMO_TOOLS_ENABLED`

- `Settings.demo_tools_enabled` (env `DEMO_TOOLS_ENABLED`, default `false`,
  repr'de görünür). `main.py` demo router'ını YALNIZ flag açıkken mount eder —
  kapalıyken OpenAPI'de ve saldırı yüzeyinde hiç yok.
- Tripwire (repo'da `APP_ENV` yok; Plan 10 uygulanırsa ona bağlanır):
  `demo_tools_enabled and session_cookie_secure` ise mount REDDEDİLİR +
  structured warning (secure cookie = prod proxy'si).
- `routers/demo_tools.py` (hepsi authenticated session ister; mutation'lar
  scalar-only audit'li):
  - `GET /api/demo/status` → `{demo_tools_enabled: true}` (flag kapalıyken 404 —
    bu 404 frontend'in gate'idir).
  - `POST /api/demo/transactions/{id}/advance` `{target_state}` →
    `demo_scenarios.advance` (karşı taraf adına, yalnız gerçek servislerle).
  - `POST /api/demo/scenarios` `{scenario}` → adlandırılmış state'te taze transaction.
- **Demo-gated OLMAYAN gerçek ürün ucu** (davet linki kaybı gerçek kullanıcı
  sorunu): `GET /api/transactions/{id}/invitations` (creator-scoped liste:
  id/rol/e-posta/durum/tarih) + `POST .../invitations/{id}/reissue` (mevcut
  supersede semantiğiyle taze `invite_link` bir kez döner) —
  `routers/invitations.py` + `services/invitations.py`.
- Frontend: bootstrap'ta `/api/demo/status` probe (`api/demo.ts`); 404 → hiçbir
  demo UI render edilmez. Açıkken: `TransactionShell` içinde floating `DemoPanel`
  (advance + davet linkleri) ve `/demo` rotası (senaryo matrisi).
- Güvenlik notları (router docstring + ARCHITECTURE'a yazılır): demo uçları asla
  payment provider çağırmaz, `funding_units`/pool payment satırı yazmaz,
  validator/policy-lock/ratification gate'lerini bypass etmez; `settled`'a yalnız
  `settlement.evaluate_settlement` üzerinden ulaşır.

### D4 — Frontend redesign (demo etkisine göre sıralı)

1. **`src/lib/lifecycle.ts`** — tek doğruluk kaynağı: `statusMaps.ts` +
   `overviewProjection.ts::stateNotice` birleşir → `canonical_state →
   {stepIndex, stepLabel, description, nextAction:{label, targetSection, role,
   blockedReason?}}`. Saf fonksiyon + vitest.
2. **TransactionShell:** yatay lifecycle stepper (Yükleme → Taraflar → Politika →
   Onay → Fonlama → Teslimat → Kapanış; tamamlanan adım yeşili `#51b206`, aktif
   adım indigo) + rol-farkındalıklı **"Sıradaki adım" kartı** ("senin aksiyonun:
   X sekmesinde Y" / "karşı taraf bekleniyor"). `awaiting_review` çıkmazına gerçek
   yönlendirme kartı.
3. **Design token'ları:** `index.css`'e Tailwind 4 `@theme` bloğu — referanstaki
   palet (`--color-primary: #3e30d9`, `--color-positive: #51b206`,
   `--color-surface: #f1f3f7`, beyaz kart, radius skalası) + Urbanist font;
   `color-scheme: light`. `pages/shared.tsx` buton/input sınıfları token'lara
   geçer; tüm sayfalardaki dark utility'ler taranıp açık temaya taşınır.
   İmplementasyonda frontend-design skill kullanılır.
4. **SectionNav:** referanstaki pill dili (aktif sekme dolgulu indigo pill) +
   `badge?: "action"|"waiting"|"done"` ve `muted` (lifecycle.ts'ten türetilir);
   sekmeler tıklanabilir kalır (yumuşak gating).
5. **Ratification sayfası** üç okunur adıma bölünür
   (`pages/transactions/ratification/`): `PolicyLockStep`, `PackageReadinessStep`
   (backend hazırlık koşullarını aynalayan checklist), `RatifyStep` (iki tarafın
   durumu).
6. **Davet linki UX:** parties sayfasında davet listesi (yeni endpoint) + kopyala
   + "yeniden oluştur" (reissue); create sayfasındaki tek seferlik link kalır ama
   "Taraflar sayfasından yeniden üretebilirsiniz" notu eklenir.
7. **Layout rework:** transaction list state-gruplu, satırda mini-stepper ve
   referanstaki stat-kart deseni (ikon + etiket + büyük değer + yeşil delta);
   overview'da sıra: sıradaki-adım kartı → KeyValueGrid → Timeline. `LoadingPanel`
   yerine skeleton bileşenleri.

## Fazlama (2 kişi, PR boyutunda)

| Faz | Kim | Efor | İçerik | Test |
|---|---|---|---|---|
| **P0** Delivery fixture | A | S (~2h) | `services/extraction.py` (marker + `_fake_fixture_delivery` + `LLM_FAKE_PROFILE`), `config.py`, `code/data/demo/` | profil seçimi; şema snapshot değişmedi; delivery fixture → funding schedule uçtan uca |
| **P1** Senaryo servisi + CLI | A | M (~4h) | `services/demo_scenarios.py`, `scripts/seed_demo_scenarios.py` | her hedef state gerçek servislerle beklenen `canonical_state`'e ulaşır; settled yolunda release-guard artefaktları (instruction'lar, approved unit'ler); idempotent re-run |
| **P2** Demo router + davet uçları | A | M (~4h) | `routers/demo_tools.py`, `main.py` koşullu mount + tripwire, invitation list/reissue (`routers/invitations.py` + servis) | flag off → 404 + OpenAPI'de yok; secure-cookie reddi; advance gerçek 409'u geçirir; reissue supersede; audit satırları |
| **F1** lifecycle.ts + stepper + tema | B (P0–P2 ile paralel) | L (~8h; dark→light geçişi dahil) | `lib/lifecycle.ts`, `TransactionShell.tsx`, `index.css @theme` + Urbanist, `shared.tsx`, dark utility taraması | lifecycle map/rol vitest'leri; stepper render; mevcut statusMaps testleri taşınır |
| **F2** Overview + list rework | B | M | `TransactionOverviewPage`, `TransactionListPage`, `overviewProjection.ts` sadeleşir | projection vitest |
| **F3** Ratification split + Nav rozetleri | B | M | `ratification/` adım bileşenleri, `SectionNav.tsx` | checklist/rozet türetim testleri |
| **F4** DemoPanel + davet UX | A+B (P2 sonrası) | S-M | `api/demo.ts`, `DemoPanel`, `/demo` rotası (`AppRoutes.tsx`), `TransactionPartiesPage` davet listesi | probe 404 → panel hiç render edilmez |
| **F5** Skeleton/cila | B | S | `Feedback.tsx` skeleton'ları | smoke |

Kritik yol: P0 → P1 → P2 → F4; F1–F3 backend fazlarıyla tam paralel.
P1 + F1 sonrası sistem demolanabilir durumdadır.

## Doğrulama

- Backend: `cd code && ./.venv/bin/python -m pytest -q` her fazda tam yeşil
  (Windows: `code\.venv\Scripts\python -m pytest -q`). P1 sonrası
  `seed_demo_scenarios.py` çalıştırılıp her senaryonun UI'da doğru
  state/stepper'la göründüğü browser'dan doğrulanır.
- Frontend: `npm run lint && npm run typecheck && npm test && npm run build`;
  F1 sonrası seed'li senaryolarla stepper/sıradaki-adım kartı her state'te
  browser'da gözle doğrulanır; açık temada kontrast/okunabilirlik kontrolü.
- Uçtan uca: `DEMO_TOOLS_ENABLED=true` ile TEK oturumda upload → settled;
  flag kapalıyken demo izlerinin (OpenAPI, UI, network) tamamen yok olduğu doğrulanır.

## Doc-sync

- ARCHITECTURE §4.1: invitation list/reissue + demo uçları (demo-flag notuyla);
  §2: `LLM_FAKE_PROFILE`, `DEMO_TOOLS_ENABLED`; §6'ya demo-araçları güvenlik notu.
- AGENTS.md "Pratik notlar": senaryo seeder'ı + demo panel + yeni tema tek satır.
- Uygulama bitince bu dosyaya durum bloğu işlenir ve `plans/done/`a taşınır.
