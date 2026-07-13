# M4Trust

M4Trust, B2B sözleşmelerini oluşturulmalarından teslimat ve ödemeye kadar izleyen bir işlem yönetimi uygulamasıdır. Sözleşmeden taraf ve kural çıkarımı yapar; tüzel kişi, davet, çift taraflı onay, fonlama, teslimat kanıtı, itiraz ve mutabakat akışlarını tek bir işlem kaydı üzerinde birleştirir.

> Proje aktif geliştirme aşamasındadır. Varsayılan yerel yapılandırma gerçek ödeme, e-posta, LLM veya video servisine çıkmadan `fake`/`mock` sağlayıcılarla çalışır.

## Neler gösterilebilir?

- Hesap, oturum ve tüzel kişi yönetimi
- Sözleşme yükleme ve AI destekli taraf/kural çıkarımı
- Karşı taraf daveti, katılımcı profilleri ve iki taraflı onay
- İşlem politikası, paket hazırlığı ve ratifikasyon
- Fonlama birimleri ve ödeme kayıtları
- E-irsaliye ve video kanıtıyla tam veya kısmi teslimat
- İtiraz, release bloklama, mutabakat, undo/refund ve kapanış
- Hazır demo matrisiyle farklı yaşam döngüsü durumlarına doğrudan geçiş

## Teknoloji ve dizin yapısı

| Alan | Teknoloji / konum |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLite — `code/backend/` |
| Frontend | React 19, TypeScript, Vite, Tailwind — `code/frontend/` |
| Yerel veri | SQLite ve yüklenen belgeler — `code/data/runtime/` (Git'e girmez) |
| Yardımcı komutlar | Seed, demo ve bakım araçları — `code/scripts/` |
| Tasarım belgeleri | `ARCHITECTURE.md`, `docs/`, `plans/` |
| LLM benchmark | Araştırma eki — `local-llm-benchmark/` |

Backend başlangıçta sürümlü SQLite migration'larını uygular. SQLite kullanıldığı için uygulamayı yerelde **tek worker** ile çalıştırın. Frontend geliştirme sunucusu `/api` isteklerini varsayılan olarak `http://127.0.0.1:8000` adresine yönlendirir.

## Hızlı kurulum (Windows / PowerShell)

Gereksinimler:

- Git
- Python 3.12
- Node.js 22 ve npm 10+

Repo kökünde PowerShell açın.

### 1. Backend ortamını hazırlayın

```powershell
Set-Location code
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ci.txt
Copy-Item backend\.env.example .env
```

Uygulama, tüzel kişi verilerini şifrelemek için iki bağımsız anahtar ister. Aşağıdaki komutu **iki kez** çalıştırın:

```powershell
.\.venv\Scripts\python.exe -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

Üretilen değerleri `code/.env` içindeki alanlara ayrı ayrı yazın:

```dotenv
APP_ENCRYPTION_KEY=ilk_üretilen_değer
APP_HMAC_KEY=ikinci_üretilen_değer
SESSION_COOKIE_SECURE=false
```

`.env` dosyasını commit etmeyin. Yerel varsayılanlar `LLM_PROVIDER=fake`, `VIDEO_PROVIDER=fake`, `PAYMENT_PROVIDER=mock` olduğundan harici API anahtarı gerekmez. Ağır RAG/video bağımlılıkları temel demo için zorunlu değildir.

### 2. Backend'i başlatın

İlk terminalde, `code/` dizinindeyken:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

- Sağlık kontrolü: <http://127.0.0.1:8000/health>
- API dokümanı: <http://127.0.0.1:8000/docs>

### 3. Frontend'i başlatın

İkinci terminalde, repo kökünden:

```powershell
Set-Location code\frontend
npm install
npm run dev
```

Arayüzü <http://127.0.0.1:5173> adresinden açın. Frontend için ayrıca bir env dosyası zorunlu değildir.

## Hazır demo sistemi

Uygulamanın farklı aşamalarını elle sıfırdan üretmeden göstermek için `code/.env` dosyasına şunu ekleyin:

```dotenv
DEMO_TOOLS_ENABLED=true
SESSION_COOKIE_SECURE=false
```

Backend kapalıyken veya yeniden başlatmadan önce, `code/` dizininde seed komutunu çalıştırın:

```powershell
.\.venv\Scripts\python.exe scripts\seed_demo_scenarios.py
```

Bu komut idempotenttir; yeniden çalıştırılması aynı demo kayıtlarını çoğaltmaz. Hazırlanan başlıca durumlar: inceleme bekliyor, ratifikasyon bekliyor, aktif/fonlanmış, kısmi teslimat, kapanmış ve itirazlı.

Demo hesapları:

| Kullanıcı | Parola | Tüzel kişi |
| --- | --- | --- |
| `berke@m4trust.demo` | `Demo12345!` | ABC |
| `yusuf@m4trust.demo` | `Demo12345!` | XYZ |

Backend ve frontend çalışırken Berke hesabıyla giriş yapın, tüzel kişiyi seçin ve `/demo` sayfasını açın. Buradaki kartlar sizi doğrudan ilgili işlem ve sekmeye götürür. Normal uçtan uca akış ise şöyledir:

1. Yeni işlem ekranında sözleşme yükleyin ve karşı tarafı davet edin.
2. Taraflar ekranında profilleri ve davet durumunu gösterin.
3. Kurallar ekranında çıkarımı ve manuel inceleme gerektiren noktaları gösterin.
4. Onay ekranında politika → paket → iki taraflı ratifikasyon zincirini ilerletin.
5. Ödemeler ekranında oluşan fonlama birimlerini gösterin.
6. Teslimat ekranında e-irsaliye/video kanıtı ve kısmi teslimat kilometre taşlarını gösterin.
7. İtirazlı senaryoda release bloklamayı; başarılı senaryoda mutabakat ve kapanışı gösterin.

Demo araçları yalnız yerel gösterim içindir. `DEMO_TOOLS_ENABLED` kapalıyken demo API rotaları ve arayüz paneli görünmez; `SESSION_COOKIE_SECURE=true` iken demo router ayrıca mount edilmez.

## Faydalı dokümanlar

- [Mimari ve sistem davranışı](ARCHITECTURE.md)
- [Backend ayrıntıları](code/backend/README.md)
- [Frontend rotaları ve davranışları](code/frontend/README.md)
- [Güvenlik ve gizlilik](docs/security-and-privacy.md)
- [Yedekleme ve veri saklama](docs/operations-retention-backup.md)
- [PostgreSQL'e geçiş hazırlığı](docs/postgresql-readiness.md)
- [Yol haritası](YOL_HARITASI.md)

## Önemli çalışma notları

- SQLite çalışma zamanı nedeniyle birden fazla uvicorn worker kullanmayın.
- Gerçek servis kimliklerini ve `code/.env` dosyasını repoya eklemeyin.
- Varsayılan mock/fake sağlayıcılar para transferi, e-posta veya harici AI çağrısı yapmaz.
- Runtime verisi `code/data/runtime/` altında tutulur ve kaynak kodun parçası değildir.
- Production kurulumu için HTTPS, güvenli cookie, gerçek secret yönetimi, kalıcı bildirim/ödeme sağlayıcıları ve operasyon dokümanlarındaki kontroller ayrıca yapılandırılmalıdır.

Katkı veya derin teknik inceleme öncesinde [AGENTS.md](AGENTS.md) içindeki güncel uygulama kararlarını ve ilgili `plans/done/` kayıtlarını okuyun.
