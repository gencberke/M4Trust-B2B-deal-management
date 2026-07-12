# M4Trust — Demo Video Prompts (Gemini / Veo)

İki video, ikisi de fotogerçekçi (photorealistic), belgesel/gerçek-hayat hissiyatında olacak şekilde tasarlandı. Türkiye ortamı: TR plaka formatı, Türkçe ekran metinleri, Türkçe iş ortamı detayları.

---

## 🎬 VIDEO 1 — Sözleşme Yükleme & Onay Akışı (Ofis Senaryosu)

### Sahne 1 — Satıcı tarafı, sözleşme yükleme:

```
Photorealistic, documentary-style corporate video, shot on a cinema camera with
shallow depth of field, natural window lighting, 4K, no visible text glitches.

Scene: Modern Turkish office interior, mid-morning. A man in his mid-30s,
business casual (light blue shirt, no tie, short well-groomed beard), sits at
a clean desk in front of a laptop. The laptop screen clearly shows a web
application called "M4Trust" with a Turkish interface — a button labeled
"Sözleşme Yükle" (Upload Contract). He clicks it, a file picker opens, he
selects a PDF named "Tedarik_Sozlesmesi_2026.pdf", drags it into the upload
zone. A progress bar fills, then a green checkmark appears with the text
"Sözleşme Başarıyla Yüklendi". He nods slightly, satisfied, leans back in his
chair. Warm, realistic office ambiance — a Turkish flag desk ornament, a
coffee cup, blurred plants in the background. Camera: slow push-in on his face
then screen, handheld micro-movement for realism, no artificial smoothness.
```

### Sahne 2 — Alıcı tarafı, sözleşme onayı:

```
Photorealistic, documentary-style corporate video, natural office lighting,
4K, shallow depth of field, subtle handheld camera movement for authenticity.

Scene: A different modern Turkish office, afternoon light through blinds
casting soft shadows. A woman in her early 30s, professional attire (navy
blazer, hair in a low bun), sits at her desk. Her laptop shows a notification
popup: "Yeni Sözleşme Onayınızı Bekliyor". She clicks it, the M4Trust web app
opens showing a contract preview with Turkish legal text, commercial terms,
and payment milestones clearly laid out on screen. She scrolls down slowly,
reading carefully, her eyes moving across the screen, occasionally nodding.
She reaches the bottom and clicks a green button labeled "Onayla" (Approve).
A confirmation banner appears: "Sözleşme Onaylandı — Karşı Taraf
Bilgilendirildi". She smiles slightly and picks up her phone to send a quick
message. Realistic skin tones, natural color grading, no CGI look, candid
unscripted body language.
```

**İpucu:** Bu iki sahneyi arka arkaya kurgularsan (satıcı yüklüyor → kesme → alıcı onaylıyor), "sözleşme dijital olarak uçtan uca yönetiliyor" mesajını net verir.

---

## 🎬 VIDEO 2 — Depo/Sanayi Sahası: Teslimat Doğrulama (Koli/Palet Sayımı)

### Sahne 1 — Dış mekan, sanayi/depo girişi:

```
Photorealistic, ultra-realistic documentary footage, shot handheld with
natural slight camera shake, overcast daylight, shot on location in a Turkish
industrial zone (sanayi sitesi), 4K, realistic dust and ambient warehouse
atmosphere, no stylization.

Scene: Exterior of a mid-size logistics warehouse in an industrial district
in Turkey. A white delivery truck is parked near the loading dock, rear doors
open, with a clearly visible Turkish license plate reading "34 ABC 1234" in
the correct TR plate format (blue EU strip on the left with "TR"). A forklift
operator in an orange high-visibility vest and white hard hat drives a
forklift carrying a wrapped pallet toward the warehouse entrance. Background:
stacked shipping containers, corrugated metal warehouse walls, a faded
Turkish flag on a pole. Natural ambient warehouse sounds implied through
visual motion blur on the forklift wheels. Realistic weathered concrete
floor with tire marks and light dust.
```

### Sahne 2 — İç mekan, koli/palet sayım videosu çekimi:

```
Photorealistic, ultra-realistic handheld smartphone POV footage style,
warehouse interior, cool industrial fluorescent lighting mixed with daylight
from high windows, 4K, authentic unpolished documentary feel, visible minor
lens shake typical of a phone camera.

Scene: Inside a large Turkish warehouse, rows of shrink-wrapped pallets and
stacked cardboard boxes extend down an aisle, each pallet labeled with
barcode stickers and Turkish shipping labels ("Alıcı:", "Miktar:", "Parti
No:"). A warehouse worker in his 40s, wearing an orange high-visibility vest
over a grey t-shirt and a white hard hat, holds a smartphone up with both
hands and walks slowly down the aisle, panning the camera left to right
across each pallet and box stack methodically, as if documenting delivered
quantity for a contract compliance check. He pauses briefly at a damaged
corner of one box, tilting the phone closer to capture the damage clearly,
then continues. His badge reads "Depo Sorumlusu" in Turkish. Realistic
warehouse ambient details: pallet jacks, safety cones, a hanging shelf
inventory sign in Turkish, dust particles visible in a light beam.
```

### Sahne 3 — Uygulamaya yükleme, sonuç ekranı:

```
Photorealistic close-up smartphone screen recording style, realistic UI
rendering, natural hand holding the phone, indoor warehouse lighting
reflecting slightly on the screen glass, 4K.

Scene: Close-up of the same warehouse worker's hands holding a smartphone.
The screen shows the "M4Trust" mobile web app with a Turkish interface: a
button labeled "Teslimat Kanıtı Yükle" (Upload Delivery Evidence). He taps
it, selects the just-recorded video file, and an upload progress bar appears
with the text "Video Analiz Ediliyor...". After a moment, the screen updates
to show "Koli Sayımı: 48/50 — Uyumlu" and a green banner reading "Teslimat
Sözleşme Şartlarına Uygun Bulundu". The worker exhales with relief, gives a
small thumbs-up gesture toward a colleague off-screen. Realistic screen glare,
authentic finger movement on glass, natural daylight through a nearby window
reflecting faintly on his safety vest.
```

**İpucu (TR plaka format notu):** Gerçek TR plaka formatı `İİ H NNNN` veya `İİ HH NNN` şeklindedir (örn. `34 ABC 1234`, `06 AB 123`). Prompt'larda bunu net yazdım; model bazen hatalı format üretebilir — çıktıyı kontrol edip gerekirse "34 ABC 1234 format Turkish plate, blue EU band with TR" ekini vurgulayarak tekrar dene.

---

## Genel öneriler

- **Uzunluk:** Çoğu Veo/Gemini video modeli tek seferde ~5-8 saniye üretir. Yukarıdaki her "sahne" ayrı bir üretim olarak düşünülmüş; sunum için bunları video düzenleme programında (örn. CapCut, Premiere) art arda kurgula.
- **Tutarlılık:** Aynı karakterin farklı sahnelerde aynı görünmesi modelin garantisi değildir. Gerekirse prompt'un başına "the same man from the previous shot, same shirt and beard" gibi referans ekleyebilirsin (bazı Gemini sürümleri karakter tutarlılığını kısmen destekler).
- **Gerçekçilik anahtar kelimeleri** (`photorealistic`, `documentary-style`, `handheld`, `natural lighting`, `no CGI look`, `4K`) bilinçli olarak her prompt'ta tekrar edildi — bu modelin "sinematik/animasyon" tonuna kaymasını engelliyor.
- **Türkçe ekran metinleri:** Modelin ekran metnini bazen bozuk/yanlış render etmesi olası (video modelleri metin konusunda zayıftır). Gerekirse bu ekran görüntülerini gerçek uygulamandan screen-record edip videoya post-prodüksiyonda bindirmen daha güvenilir sonuç verir.
