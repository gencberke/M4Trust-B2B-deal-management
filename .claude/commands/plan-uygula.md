---
description: Bir planı ARCHITECTURE.md'ye uygun şekilde uygula, ardından dokümantasyonu senkronla (doc-sync)
argument-hint: plans/ready/<plan>.md
---

Görev: `$ARGUMENTS` plan dosyasını uçtan uca uygula ve dokümantasyonu taze bırak. Sırayla:

1. **Bağlamı yükle:** `AGENTS.md`, `ARCHITECTURE.md` ve `$ARGUMENTS` dosyasını oku.

2. **Ön kontrol (implementasyondan önce):**
   - Dosya `plans/ready/` altında değilse: `plans/planning/` altındaysa henüz olgunlaşmamış bir taslaktır — kullanıcıya taslağı uygulamak istediğinden emin olup olmadığını sor, onaysız ilerleme; `plans/done/` altındaysa zaten uygulanmıştır — kullanıcıyı bilgilendir ve ne istediğini netleştir.
   - Planı ARCHITECTURE.md ile karşılaştır. Plan, §6 "dışına çıkılmayacak tasarım kalıpları"ndan birini deliyorsa DUR ve kullanıcıya seçenekleriyle birlikte bildir.
   - Mimaride henüz tanımlı olmayan yenilikler (endpoint, servis, bağımlılık, event, şema alanı…) varsa bunları "doc-sync listesi" olarak not et.

3. **Uygula:** Planı mimarideki interface ve contract'lara uyarak implemente et. Adapter + fake kalıbını koru. Yaptığını çalıştırarak doğrula (test veya manuel akış); sonucu rapora yaz.

4. **Doc-sync (zorunlu — işin parçası):** Değişikliklerini şu haritayla dokümana yansıt:
   - Yeni/değişen REST endpoint → ARCHITECTURE §4.1
   - Extraction JSON şeması değişikliği → ARCHITECTURE §4.2 (ikili sözleşme — kullanıcı mutabakatı olmadan değiştirme)
   - Yeni event tipi → ARCHITECTURE §4.3
   - Yeni servis/modül/dosya → ARCHITECTURE §1 dizin haritası
   - Yeni bağımlılık/teknoloji/model → ARCHITECTURE §2 tech stack
   - DB tablosu / state machine değişikliği → ARCHITECTURE §5
   - Yeni değişmez kural → ARCHITECTURE §6 + AGENTS.md "Değişmez ilkeler" özeti
   - Korpus/vektör sayısı, boş-dosya durumu gibi pratik gerçekler → AGENTS.md "Pratik notlar"

   Güncelleme gerekmiyorsa raporda açıkça "doc-sync: değişiklik gerekmedi" yaz.

5. **Plan durumunu işle:** `$ARGUMENTS` dosyasının en üstündeki durum bloğunu güncelle:
   `> **Durum:** Uygulandı — <tarih> · Sapmalar: <planla uygulama arasındaki farklar; yoksa "yok">`
   Ardından dosyayı `plans/done/` altına taşı ve dosyaya işaret eden linkleri (AGENTS.md, ARCHITECTURE.md, plans/README.md) yeni yola güncelle.

6. **Raporla:** ne uygulandı, neler doğrulandı, hangi doküman bölümleri güncellendi, sapmalar ve açık işler.
