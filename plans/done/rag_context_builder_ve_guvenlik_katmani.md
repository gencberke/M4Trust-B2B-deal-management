# RAG Context Builder ve Güvenlik-Aware Retrieval Katmanı

> **Durum:** Uygulandı — 2026-07-09 · Sapmalar: (1) `--k` yalnızca deprecated `--collection` debug yolunda etkili — ContextBuilder modunda temel query k'ları tasarımca sabit 3 (pinlenmiş `build()` imzası korundu). (2) `security_controls` koleksiyonu **embed edilmedi** — ortamda ağır RAG deps (chromadb/FlagEmbedding) yok; chunk'lar hazır (`chunks/security/pci_dss_control_map.json`, 6 kontrol), `build_rag.py` çalışınca oluşur (plan bunu bloker saymıyordu). (3) `config.security_collection` faz bağımsızlığı için Faz 1'de `getattr` fallback, Faz 3'te gerçek alan olarak eklendi. Doğrulama: 91 test yeşil + CLI smoke (normal + CVV/openai blocking) davranışsal doğrulandı.

> **Tür:** Uygulama planı (taslak — onay bekliyor).
> **Kaynak:** 09.07.2026 RAG revizyon oturumu; [regulasyon_rag_genisletmesi](regulasyon_rag_genisletmesi.md) planının kalan kalemlerini devralır ve genişletir.
> **Ekip kararları (09.07.2026):** kapsam = Faz 1+2+3 (validator hariç) · `ExtractionService.extract()` imzası `ContextPack`'e geçer (§3.1 doc-sync ile) · PCI DSS dar kapsamlı kontrol haritası olarak yeniden kapsama alındı.
> **Revizyon (09.07.2026, ekip dönütü):** `--collection` deprecated (kaldırılmıyor) · blocking'de deterministik `ExtractionResult` fallback'i pinlendi · skor=distance semantiği netleştirildi · security koleksiyonu yokken graceful devam acceptance'a eklendi · Ek A'ya `pci.req.10.logging_evidence` eklendi.

## Status

done

## Goal

Mevcut RAG hattını yeniden yazmadan üstüne bir **ContextBuilder** orkestrasyon katmanı koymak: çoklu query + çoklu koleksiyon retrieval, kaynak-tipli LLM context formatı, koşullu `security_controls` koleksiyonu ve kart verisi için deterministik privacy guardrail'leri. Amaç, LLM'in önerilerini kanıtlanabilir kaynaklara bağlamak ve dış LLM'e gitmemesi gereken veriyi LLM yorumuna bırakmadan engellemek.

## Background

Mevcut durum (kodla doğrulandı, 09.07.2026):

- `scripts/extract_contract.py:78` — maskelenmiş metnin ilk 1000 karakteri **tek query** olarak kullanılıyor; **tek koleksiyon** (`legal_articles`), default k=5.
- `services/extraction.py:125` — chunk metinleri kaynak bilgisi olmadan düz birleştirilip `"İlgili mevzuat:"` başlığıyla gönderiliyor. LLM hangi metnin kanun/tebliğ/örnek sözleşme olduğunu ayırt edemiyor.
- `services/rag.py` — `Retriever.retrieve(query, collection, k)` düşük seviye Chroma aracı olarak sağlam; lazy BGE-M3, testli, DI'lı. **Değişmesi gerekmiyor.**
- `services/privacy.py` — IBAN/EMAIL/PHONE/TCKN/VKN maskeliyor (`mask() → MaskResult`, `restore()`). Kart verisi (PAN, CVV, track data, PIN) kapsam dışı.
- Chroma index: `legal_articles` (891 vektör) + `contract_examples` (395 vektör). Üçüncü koleksiyon yok.
- Devralınan plan ([regulasyon_rag_genisletmesi](regulasyon_rag_genisletmesi.md)) iki açık kalem bırakmıştı: PCI DSS özeti (kapsam dışı bırakılmıştı — bu planda dar kapsamla geri alındı) ve validator hassas-veri kontrolü (**backend iskeleti planına devredildi**, bu planda yok).

## Problem

1. **Tek query yetersiz:** sözleşmenin ilk 1000 karakteri çoğunlukla taraf/tanım/giriş içerir; ödeme şartları, teslimat kanıtı, ceza/temerrüt, veri işleme maddeleri sonra gelir ve retrieval bunları ıskalar.
2. **Tek koleksiyon:** `contract_examples` (clause yapısı için) ve güvenlik bağlamı aynı retrieval turunda kullanılmıyor.
3. **Düz context:** LLM kaynak tipini ayırt edemediği için "kaynağa dayalı, açıklanabilir öneri" ürün vaadi promptta karşılıksız kalıyor.
4. **Kart verisi guardrail'i yok:** PAN/CVV/track/PIN yakalanmıyor; §6.7 sınırı bu tipler için tanımsız. Güvenlik kararı LLM'e bırakılamaz — deterministik olmalı.

## Non-goals

- **Validator (`validator.py`) bu planda yazılmaz** — backend iskeleti planının işidir. Eski plandaki "extraction çıktısında maskelenmemiş hassas alan → NEEDS_REVIEW" kalemi de oraya devredilir.
- Reranker / cross-encoder yok; LLM tabanlı query planner yok (rule-based yeterli).
- `Retriever` ve `build_rag.py`'nin embed mantığı yeniden yazılmaz; mevcut iki koleksiyon yeniden embed edilmez.
- §4.2 extraction JSON şemasına alan eklenmez/çıkarılmaz (ikili sözleşme donuk kalır).
- PCI DSS **ham metni** hiçbir şekilde repoya/Chroma'ya girmez (lisans sınırı).
- FastAPI/DB/event entegrasyonu yok — hat CLI seviyesinde kalır.

## Proposed design

Hedef akış (değişen kısımlar işaretli):

```text
Markdown → privacy.analyze()  ← YENİ: PrivacyReport (mask + kart verisi sınıflandırma)
        → ContextBuilder.build(masked_md, privacy_report)  ← YENİ
            ├─ rule-based query planning (sabit + sinyal-tetiklemeli)
            ├─ legal_articles + contract_examples retrieval
            ├─ security_controls retrieval (yalnızca risk sinyali varsa)  ← YENİ koleksiyon
            └─ dedupe + kota + karakter limiti → ContextPack
        → ExtractionService.extract(masked_md, context_pack)  ← imza değişir
        → restore (kart-verisi placeholder'ları ASLA restore edilmez)
```

### ContextBuilder (`services/context_builder.py`, yeni)

Veri yapıları (frozen dataclass):

```python
SourceType = Literal["legal", "contract_example", "security"]

@dataclass(frozen=True)
class RetrievalQuery:
    text: str; purpose: str; collection: str; k: int

@dataclass(frozen=True)
class ContextSource:
    source_type: SourceType; source: str; text: str; score: float
    collection: str; madde_no: str | None = None; heading: str | None = None

@dataclass(frozen=True)
class ContextPack:
    queries: list[RetrievalQuery]
    sources: list[ContextSource]
    formatted_for_llm: str
    risk_flags: list[str]
```

`ContextBuilder(settings, retriever).build(masked_markdown, privacy_report=None) -> ContextPack`. Retriever'a dokunmaz, onu kullanır. Retriever kurulamazsa / hata verirse mevcut graceful degradation korunur: boş `ContextPack` ile bağlamsız devam.

**Query planlama (rule-based):**

- Sabit temel query'ler (`legal_articles`, k=3): (1) "ödeme şartları ödeme hizmeti fon aktarımı taraf yükümlülükleri", (2) "teslimat mal teslimi hizmet ifası kabul ayıplı mal", (3) "gecikme temerrüt cezai şart iade fesih".
- Sinyal-tetiklemeli ek query'ler (`legal_articles`, k=3, maskelenmiş metinde anahtar kelime aramasıyla):

| Sinyal (metinde geçen) | Ek query |
|---|---|
| `kişisel veri`, `müşteri bilgisi`, `hassas veri`, `KVKK` | "kişisel veri işleme hassas müşteri verisi veri paylaşımı" |
| `dış hizmet`, `bulut`, `API`, `yurt dışı` | "dış hizmet alımı yurt dışı veri aktarımı veri lokalizasyonu" |

- `contract_examples`: 1 query (maskelenmiş metnin ilk 1000 karakteri — mevcut davranış), k=2.
- `security_controls`: **yalnızca** (a) `privacy_report.detected_types` kart-verisi tipi içeriyorsa VEYA (b) metinde `kart`, `PAN`, `CVV`, `cardholder`, `POS` sinyali varsa; 1-2 query, k=2. Sinyal yoksa bu koleksiyona hiç gidilmez.

**Packing (Faz 4'ün basit hali, builder içinde):** aynı `(source, madde_no)` ve aynı text-hash tekrarları atılır; kaynak tipi kotası `legal ≤ 6 · contract_example ≤ 2 · security ≤ 2`; `formatted_for_llm` toplamı ~12.000 karakteri aşarsa en alakasız kaynaklar düşürülür.

> ⚠️ **Skor semantiği:** mevcut `Retriever`'da `Chunk.score` Chroma **distance**'ıdır (`rag.py:74`) — **düşük değer daha iyi**. `ContextSource.score` aynı semantiği taşır: kota içinde en düşük distance'lılar seçilir, limit aşımında en **yüksek** distance'lılar düşürülür. Implementer bunu similarity sanıp sıralamayı ters çevirmemeli; mevcut Retriever sıralaması korunur.

**LLM formatı** (`formatted_for_llm`): her kaynak `[LEGAL_SOURCE_n] / [CONTRACT_EXAMPLE_n] / [SECURITY_CONTROL_n]` etiketiyle, `collection · source · madde_no/heading · score · text` alanlarıyla yazılır (girdi dokümanı §10'daki format).

### security_controls koleksiyonu

- `config.py`: `security_collection: str = "security_controls"` (env `RAG_SECURITY_COLLECTION`).
- `build_rag.py`: mevcut `contracts → contract_examples` eşlemesine `security → security_controls` dalı eklenir.
- İçerik: `code/data/processed/markdown/security/pci_dss_control_map.md` — **kendi cümlelerimizle** dar kapsamlı runtime kontrol haritası (6 kontrol; taslak metin bu planın Ek A'sında hazır). Chunk'lama `## kontrol_id` başlık yapısıyla yapılır — implementer, `chunk_documents.py`'nin başlık stratejisinin bu dosyayı kontrol başına bir chunk olarak böldüğünü doğrulamalı (MADDE deseni burada yok).

### Privacy genişletmesi (`services/privacy.py`)

Yeni tespit tipleri ve aksiyonları:

| Tip | Tespit | Aksiyon |
|---|---|---|
| PAN | 13-19 hane (boşluk/tire gruplu dahil) + **Luhn doğrulaması** | Maskele; placeholder **restore edilmez** |
| CVV/CVC | bağlam-duyarlı (yakında `cvv`, `cvc`, `güvenlik kodu` geçen 3-4 hane) | **Blocking finding** — dış LLM çağrısı yapılmaz |
| Track data | `%B...^...^` / `;PAN=...?` desenleri | **Blocking finding** |
| PIN | bağlam-duyarlı (`pin`, `pin blok` yakınında 4-12 hane) | **Blocking finding** |
| Expiry + PAN birlikte | `MM/YY` deseni, PAN tespitliyken | risk flag (`CHD_CONTEXT`) |

Yeni API — mevcut `mask()/restore()` **bozulmaz**, üstüne eklenir:

```python
@dataclass
class PrivacyReport:
    masked_text: str
    mapping: dict[str, str]        # restore edilebilir placeholder'lar (kart verisi HARİÇ)
    detected_types: set[str]
    blocking_findings: list[str]   # ör. ["CVV tespit edildi"]
    risk_flags: list[str]          # ör. ["CHD_CONTEXT"]

def analyze(text: str) -> PrivacyReport   # içinde mask()'ı kullanır
```

Kritik kurallar: kart-verisi placeholder'ları `mapping`'e **girmez** (restore hiçbir koşulda kart verisini geri açamaz — sadeleşmiş DO_NOT_RESTORE). `blocking_findings` boş değilse **canlı (openai) provider çağrılmaz**. Fake provider çalışmaya devam edebilir (dışarı veri gitmiyor).

**Blocking'de deterministik fallback (tip tutarlılığı):** LLM çağrısı atlandığında CLI seviyesinde string basılarak geçiştirilmez; mevcut `ExtractionResult` tipiyle üretilir:

```python
ExtractionResult(
    status="needs_review",
    data=None,   # sahte/boş ExtractionJSON üretilmez — parties/contract_id zorunlu alanlar uydurulamaz
    reason="Hassas ödeme doğrulama verisi tespit edildi; dış LLM çağrısı atlandı: " + "; ".join(blocking_findings),
)
```

`privacy_report.risk_flags` + `blocking_findings` CLI'ın dayanaklar/rapor çıktısında ayrıca gösterilir (risk_flags'in extraction JSON'a birleştirilmesi yalnızca `data` doluyken geçerlidir).

### ExtractionService imza değişikliği (ekip kararı, §3.1 doc-sync)

```python
# eski: extract(masked_markdown: str, rag_context: list[Chunk]) -> ExtractionResult
# yeni:
extract(masked_markdown: str, context: ContextPack | None) -> ExtractionResult
```

`_build_messages` artık chunk birleştirmez; `context.formatted_for_llm`'i tek system mesajı olarak ekler. System prompt'a şu yönerge satırları eklenir: "Aşağıdaki kaynaklar retrieval sistemi tarafından seçilmiştir. Yalnızca bu kaynakları sözleşme metniyle birlikte kullan. Kaynaklarda olmayan hukuki iddiaları kesin hüküm gibi sunma. Ödeme kararı verme; sadece kural öner." `FakeExtractionService` aynı imzaya geçer. `context=None` veya boş pack → bağlamsız çağrı (mevcut davranış).

### CLI (`scripts/extract_contract.py`)

- `mask()` yerine `analyze()`; `retriever.retrieve(...)` yerine `ContextBuilder.build(...)`.
- `--collection` bayrağı **kaldırılmaz, deprecated olur**: verilmezse default davranış ContextBuilder'dır; verilirse deprecation uyarısı basılır ve eski tek-koleksiyon yoluna (builder bypass, mevcut davranış) düşülür — Chroma koleksiyonlarını tek tek debug etmek için de işlevsel. Mevcut CLI testleri kırılmaz. `--k` temel query k'sını override eder.
- Çıktıya "dayanaklar" özeti eklenir: kullanılan query'ler + seçilen kaynakların `source/madde_no/score` listesi (demo anlatısının "kanıtlanabilir rule sheet" ayağı).
- `privacy_report.risk_flags`, restore sonrası extraction JSON'ının `risk_flags` listesine **birleştirilir** (şema değişmiyor, alan zaten var); blocking durumunda `needs_manual_review=true` set edilir.

## Files likely involved

- `code/backend/app/services/context_builder.py` — **yeni**: ContextBuilder + dataclass'lar
- `code/backend/app/services/privacy.py` — kart verisi tespiti + `PrivacyReport`/`analyze()`
- `code/backend/app/services/extraction.py` — imza değişikliği + kaynaklı prompt
- `code/backend/app/config.py` — `security_collection` alanı
- `code/scripts/build_rag.py` — `security/` → `security_controls` eşlemesi
- `code/scripts/extract_contract.py` — ContextBuilder entegrasyonu + dayanaklar çıktısı
- `code/data/processed/markdown/security/pci_dss_control_map.md` — **yeni** (içerik: Ek A)
- `code/tests/test_context_builder.py`, `code/tests/test_privacy_card_data.py` — **yeni**
- `code/tests/test_extraction.py`, `code/tests/test_extract_contract_cli.py` — imza/entegrasyon güncellemeleri
- `ARCHITECTURE.md`, `AGENTS.md` — doc-sync (aşağıda)

## Implementation steps

Önerilen commit sınırları: (1) adım 1-3 "ContextBuilder + kaynaklı prompt", (2) adım 4-5 "security_controls koleksiyonu", (3) adım 6-7 "kart verisi guardrail'i", (4) adım 8 doc-sync (veya her commit'e dahil).

1. `context_builder.py`: dataclass'lar + `ContextBuilder` (query planlama, çoklu retrieval, dedupe/kota/limit, `formatted_for_llm`). Retriever DI ile enjekte; testlerde fake retriever.
2. `extraction.py`: imzayı `ContextPack | None`'a geçir; `_build_messages`'ı `formatted_for_llm` kullanacak şekilde sadeleştir; system prompt yönerge satırlarını ekle; Fake'i aynı imzaya taşı; mevcut extraction testlerini güncelle.
3. `extract_contract.py`: ContextBuilder entegrasyonu, `--collection` kaldırma, dayanaklar özeti; CLI testlerini güncelle. **Bu adım sonunda tüm testler yeşil olmalı (ara kararlı nokta).**
4. `config.py` + `build_rag.py`: `security_collection` + dizin eşlemesi.
5. Ek A'daki `pci_dss_control_map.md`'yi `code/data/processed/markdown/security/` altına koy; chunk'la ve embed et (`chunk_documents.py` başlık stratejisinin kontrol başına chunk ürettiğini doğrula); ContextBuilder'ın koşullu security retrieval'ını gerçek koleksiyonla duman-testi yap.
6. `privacy.py`: PAN+Luhn, CVV/track/PIN bağlam-duyarlı tespit, `PrivacyReport`/`analyze()`; kart placeholder'ları mapping dışı. Mevcut `mask()/restore()` davranışı ve testleri değişmeden kalmalı.
7. CLI'da `analyze()`'a geçiş + blocking akışı (canlı provider'ı atla → `needs_review` + gerekçe) + risk_flags birleştirme; yeni testler.
8. Doc-sync: ARCHITECTURE §1 dizinine `context_builder.py`; §2 RAG satırına üçüncü koleksiyon; §3.1 imza güncellemesi; §3.2'ye ContextBuilder/koşullu retrieval notu; §3.5'e PrivacyReport + blocking davranışı; AGENTS "Pratik notlar"a koleksiyon/korpus güncellemesi. Bu planın durum bloğunu işleyip `plans/done/`'a taşı; [regulasyon_rag_genisletmesi](regulasyon_rag_genisletmesi.md)'nin devir notunu doğrula.

## Acceptance criteria

- Mevcut 58 test kırılmadan (imza güncellemeleri hariç davranışsal regresyon olmadan) tüm suite yeşil.
- Fake provider ile uçtan uca CLI çalışır; RAG bağımlılıkları kurulu değilse hat **bağlamsız** graceful devam eder (mevcut davranış korunur).
- `ContextPack.formatted_for_llm` içinde her kaynak koleksiyon/source etiketiyle görünür; ham mapping/PII promptta görünmez.
- Security sinyali yoksa `security_controls` koleksiyonuna hiç sorgu gitmez; sinyal varsa 1-4 security kaynağı gelir.
- `security_controls` koleksiyonu henüz build edilmemişse ContextBuilder hata fırlatmaz: security context boş kalır, legal/contract bağlamıyla devam edilir (testle doğrulanır).
- Blocking durumunda dönen değer tip-tutarlıdır: `ExtractionResult(status="needs_review", data=None, reason=...)` — CLI string basarak geçiştirmez.
- Geçerli PAN (Luhn-doğrulamalı) maskelenir ve restore çıktısında **asla** geri açılmaz; Luhn'dan geçmeyen 16 haneli sayı PAN olarak etiketlenmez.
- CVV/track/PIN tespitinde canlı LLM çağrısı yapılmaz; sonuç `needs_review` + açık gerekçe döner.
- Kota ve limitler uygulanır: legal ≤ 6, contract_example ≤ 2, security ≤ 2, toplam ~12.000 karakter.
- Doc-sync tamamlanmış (yukarıdaki bölümler güncel).

## Verification

```bash
cd code
./.venv/bin/python -m pytest -q                          # tüm suite
./.venv/bin/python -m pytest tests/test_context_builder.py tests/test_privacy_card_data.py -v
# Fake provider ile uçtan uca (RAG kuruluysa dayanaklar özeti de görünmeli):
./.venv/bin/python scripts/extract_contract.py data/raw/contracts/<ornek>.pdf
# Kart verisi blocking duman testi (CVV içeren sentetik metinle, canlı provider'da çağrının atlandığını logdan doğrula)
```

Manuel kontrol: CLI çıktısındaki dayanaklar bölümünde query'ler ve kaynak listesi; blocking senaryosunda gerekçe metni.

## Risks

- **İmza değişikliği churn'ü:** `extract()` imzası değişince mevcut extraction/CLI testleri güncellenecek — davranış regresyonu riskine karşı adım 3 sonunda ara kararlı nokta şart.
- **CVV/PIN bağlam tespitinde false positive:** B2B sözleşmelerinde "3 haneli sayı + yakında 'kod' kelimesi" tarz yanlış eşleşmeler blocking'i tetikleyip demo akışını durdurabilir. Desenler dar tutulmalı (açık `cvv/cvc/pin` anahtar kelimeleri), testlerde negatif örnekler zorunlu.
- **Chunker uyumu:** `chunk_documents.py` başlık stratejisi control-map formatını beklediğimiz gibi bölmeyebilir — adım 5'te doğrulama var; gerekirse dosya formatı chunker'a uydurulur (tersi değil).
- **Embed bağımlılığı:** security koleksiyonunu embed etmek chromadb+FlagEmbedding kurulu ortam ister (~GB'lar). Kurulu değilse adım 5 yalnızca dosya+mapping olarak iner, embed sonraya kalır — plan bunu blocker saymaz.
- **Sinyal listesinin dili:** anahtar kelime sinyalleri Türkçe; İngilizce sözleşmelerde sinyal kaçabilir. MVP'de kabul edilir risk (korpus ve demo Türkçe).

## Notes for Implementer

- Uygulama `/plan-uygula plans/ready/rag_context_builder_ve_guvenlik_katmani.md` ile yapılır; AGENTS.md'deki doc-sync protokolü işin parçasıdır, atlanamaz.
- **Görevler kişiye etiketlenmez** — sıralama yukarıdaki adım sırasıdır, tek hat yeterlidir.
- `Retriever`'a dokunma; ContextBuilder onu sarmalasın. `rag.py`'deki `Chunk` dataclass'ı retriever çıktısı olarak kalır; `ContextSource`'a dönüşüm builder içinde yapılır.
- §6.7 sırası korunur: `analyze()` (mask dahil) **her zaman** canlı LLM çağrısından önce; `blocking_findings` doluysa canlı çağrı hiç yapılmaz.
- `.env`/secrets kurallarına dokunan bir şey yok; `LLM_API_KEY` loglanmaz.
- Kod yorumları/CLI çıktısı Türkçe, tanımlayıcılar İngilizce (mevcut stil).
- Test ortamı: `cd code && ./.venv/bin/python -m pytest`. Ağır RAG bağımlılıkları kurulu olmayabilir — ContextBuilder testleri fake retriever ile bağımsız çalışmalı.

---

## Ek A — PCI DSS Kontrol Haritası taslağı (`pci_dss_control_map.md` içeriği)

> Ham PCI DSS metni değildir; ekibin kendi cümleleriyle yazılmış, requirement numarasına atıf yapan runtime kontrol haritasıdır. Kaynak: PCI DSS v4.0.1 (pcisecuritystandards.org). Gözden geçirip düzeltebilirsiniz.

```markdown
# PCI DSS Kontrol Haritası — M4Trust

Bu doküman PCI DSS v4.0.1'in M4Trust akışına dokunan gereksinimlerinin kendi
cümlelerimizle yazılmış runtime karşılıklarıdır. Ham standart metni içermez.

## pci.req.3.sad_storage

source_ref: PCI DSS v4.0.1 Requirement 3
topic: sensitive_authentication_data
applies_when: girdi CVV/CVC, tam track data veya PIN/PIN blok içeriyorsa

runtime_rule: Hassas doğrulama verisi (SAD) yetkilendirme sonrasında saklanamaz;
dış LLM sağlayıcılarına gönderilemez ve kanıt paketlerinde tutulamaz.

m4trust_action: BLOCK_EXTERNAL_LLM · DO_NOT_RESTORE · NEEDS_REVIEW

## pci.req.3.pan_protection

source_ref: PCI DSS v4.0.1 Requirement 3
topic: pan_storage_masking
applies_when: girdi kart numarası (PAN) içeriyorsa

runtime_rule: PAN saklanacaksa okunamaz hale getirilmeli; görüntülenirken
maskelenmelidir (en fazla ilk 6 / son 4 hane). M4Trust PAN'ı dış LLM'e ham
göndermez ve çıktıya geri açmaz.

m4trust_action: MASK_PAN_BEFORE_LLM · DO_NOT_RESTORE · ADD_SECURITY_RISK_FLAG

## pci.req.4.transmission

source_ref: PCI DSS v4.0.1 Requirement 4
topic: cardholder_data_transmission

runtime_rule: Kart sahibi verisi açık/genel ağlar üzerinden güçlü kriptografik
koruma olmadan iletilemez. Kart verisi gerektiren akışlar lisanslı ödeme
sağlayıcısının (Moka) barındırdığı kanala yönlendirilir.

m4trust_action: REQUIRE_PROVIDER_HOSTED_FLOW · ADD_SECURITY_RISK_FLAG

## pci.req.7.access_restriction

source_ref: PCI DSS v4.0.1 Requirement 7
topic: need_to_know_access

runtime_rule: Kart sahibi verisine erişim iş gereksinimiyle sınırlıdır
(need-to-know). M4Trust maskeleme haritasını yalnızca lokalde tutar; evidence
bundle'a maskeli hal girer.

m4trust_action: LOCAL_ONLY_MAPPING · MASKED_EVIDENCE

## pci.req.10.logging_evidence

source_ref: PCI DSS v4.0.1 Requirement 10
topic: logging_and_evidence

runtime_rule: Log ve kanıt (evidence) çıktıları ham PAN, hassas doğrulama
verisi (SAD) veya maskelenmemiş hassas veri içermemelidir. M4Trust evidence
bundle'ına yalnızca maskeli içerik girer; maskeleme haritası lokalde kalır.

m4trust_action: MASKED_LOGS_ONLY · EVIDENCE_REDACTION_CHECK · ADD_SECURITY_RISK_FLAG

## pci.req.12.third_party

source_ref: PCI DSS v4.0.1 Requirement 12
topic: third_party_service_providers

runtime_rule: Kart verisine dokunan üçüncü taraf hizmet sağlayıcıların
sorumlulukları yazılı olarak tanımlanmalıdır. M4Trust anlatısında kart verisi
işleme tamamen lisanslı sağlayıcıda (Moka) kalır; M4Trust karar-kanıt katmanıdır.

m4trust_action: DELEGATE_TO_LICENSED_PROVIDER · ADD_SECURITY_RISK_FLAG
```
