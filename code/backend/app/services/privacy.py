"""PII maskeleme/geri-yükleme — §6.7 dış-çağrı güvenlik sınırı.

Dış LLM çağrısına giden içerik yalnızca `mask()` uygulandıktan sonra gönderilir.
`restore()`, LLM'in döndürdüğü (placeholder içeren) yapıdaki değerleri orijinal
PII değerlerine geri döndürmek için kullanılır.

Yalnızca stdlib (`re`, `dataclasses`) — yeni bağımlılık yok.

Desen sırası önemlidir (rakam çakışmalarını önlemek için): IBAN -> e-posta ->
telefon -> TCKN (11 hane) -> VKN (10 hane). Daha spesifik/uzun kalıplar önce
maskelenir ki geri kalan salt rakam dizileri (TCKN/VKN) yanlış bir alt-dizeyi
(ör. IBAN veya telefon içindeki rakamları) yakalamasın.

Bilinen sınır: `+90`/başında `0` olmadan yazılan yerel bir telefon numarası
PHONE deseniyle eşleşmez ama yine de VKN/TCKN deseni tarafından maskelenir
(etiket yanlış olabilir, ancak değer yine de token'lanır — kaçak yok).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MaskResult:
    """`mask()` çıktısı: maskelenmiş metin + placeholder->orijinal eşleşmesi."""

    masked_text: str
    mapping: dict[str, str] = field(default_factory=dict)


# (PII_TIPI, derlenmiş_regex) sırası: IBAN -> EMAIL -> PHONE -> TCKN -> VKN.
# Lookbehind/lookahead ile bitişik rakam/harf dizilerinin bir parçası olarak
# eşleşme (partial match) engellenir; böylece ör. 11 haneli bir TCKN, IBAN
# içindeki rakamlarla veya 3 haneli bir miktarla (ör. "100") karışmaz.
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        # Gruplu (4'erli, boşluk/tire ayraçlı) ve bitişik IBAN biçimlerinin
        # ikisini de tek token olarak maskelemek için ayraç isteğe bağlıdır.
        "IBAN",
        re.compile(r"(?<![A-Za-z0-9])TR(?:[ -]?[0-9A-Za-z]){24}(?![A-Za-z0-9])"),
    ),
    (
        "EMAIL",
        re.compile(
            r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])"
        ),
    ),
    (
        "PHONE",
        re.compile(
            r"(?<!\d)(?:\+90|0)[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)"
        ),
    ),
    (
        # TCKN: 11 hane, ilk hane 0 olamaz (resmi format kuralı).
        "TCKN",
        re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)"),
    ),
    (
        # VKN/vergi no: 10 hane.
        "VKN",
        re.compile(r"(?<!\d)\d{10}(?!\d)"),
    ),
]


def mask(text: str) -> MaskResult:
    """Metindeki PII değerlerini deterministik `[[PII_<TIP>_<n>]]` token'larıyla değiştirir.

    Aynı orijinal değer metinde birden fazla kez geçse bile her zaman aynı
    token'a eşlenir (idempotent, değer bazlı dedupe).
    """
    value_to_token: dict[str, str] = {}
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}
    result = text

    for pii_type, pattern in _PII_PATTERNS:

        def _replace(match: re.Match[str], _pii_type: str = pii_type) -> str:
            value = match.group(0)
            token = value_to_token.get(value)
            if token is not None:
                return token
            counters[_pii_type] = counters.get(_pii_type, 0) + 1
            token = f"[[PII_{_pii_type}_{counters[_pii_type]}]]"
            value_to_token[value] = token
            mapping[token] = value
            return token

        result = pattern.sub(_replace, result)

    return MaskResult(masked_text=result, mapping=mapping)


def restore(obj: str | dict | list, mapping: dict[str, str]) -> str | dict | list:
    """`obj` içindeki placeholder'ları `mapping` ile orijinal değerlerine geri döndürür.

    `str | dict | list` üzerinde recursive çalışır; `ExtractionJSON.model_dump()`
    gibi iç içe yapılardaki her string değer içinde geçen placeholder'lar
    değiştirilir. Bunların dışındaki değerler (int, float, bool, None, vb.)
    olduğu gibi geri döner.

    Kart-verisi (`[[CARD_*]]`) token'ları `mapping`'e HİÇ girmediğinden restore
    onları asla geri açamaz (§6 / PCI DSS DO_NOT_RESTORE) — bu garanti
    `analyze()` tarafından mapping'e kart değeri konmayarak sağlanır.
    """
    if isinstance(obj, str):
        restored = obj
        for token, original in mapping.items():
            restored = restored.replace(token, original)
        return restored
    if isinstance(obj, dict):
        return {key: restore(value, mapping) for key, value in obj.items()}
    if isinstance(obj, list):
        return [restore(item, mapping) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Kart verisi (PAN/SAD) güvenlik katmanı — §6.7 + PCI DSS kontrol haritası.
#
# `mask()/restore()` DEĞİŞMEZ; `analyze()` bunun ÜSTÜNE oturur. Sıra kritiktir:
# önce standart PII maskelenir (IBAN'ın gruplu 24 hanesi PAN aday desenine
# takılıp IBAN tespitini bozmasın diye), SONRA kart verisi taranır.
#
# Kart placeholder'ları (`[[CARD_*]]`) restore edilebilir `mapping`'e ASLA
# girmez (DO_NOT_RESTORE). SAD (CVV/track/PIN) tespiti `blocking_findings`
# üretir → dış (canlı) LLM çağrısı yapılmaz; kararı CLI verir, bu modül yalnızca
# raporlar.
# ---------------------------------------------------------------------------

# Kart numarası adayı: 13-19 hane, tekil boşluk/tire ayraçlı gruplar dahil.
# Luhn doğrulaması callback'te yapılır; geçmeyen aday PAN sayılmaz.
_PAN_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")

# Track 1/2 (manyetik şerit) desenleri.
_TRACK1_RE = re.compile(r"%B\d{12,19}\^[^?\n]{0,60}\^[^?\n]{0,60}\?")
_TRACK2_RE = re.compile(r";\d{12,19}=\d{7,30}\?")

# CVV/CVC: bağlam-duyarlı (anahtar kelime yakınında 3-4 hane), iki yön.
_CVV_KW_RE = re.compile(
    r"(?i)(?:cvv2?|cvc2?|güvenlik\s+kodu|card\s+verification(?:\s+value)?)\s*[:=]?\s*(\d{3,4})(?!\d)"
)
_CVV_REV_RE = re.compile(r"(?i)(?<!\d)(\d{3,4})\s*(?:cvv2?|cvc2?)(?!\w)")

# PIN: bağlam-duyarlı (`pin`/`pin blok` yakınında 4-12 hane).
_PIN_RE = re.compile(
    r"(?i)(?:pin\s*blo(?:k|ğu)|pin\s*block|pin\s*kodu?|\bpin\b)\s*[:=]?\s*(\d{4,12})(?!\d)"
)

# Son kullanma tarihi: MM/YY veya MM/YYYY. Tek başına maskelenmez; yalnızca PAN
# ile birlikte görülürse CHD_CONTEXT risk flag'i üretir.
_EXPIRY_RE = re.compile(r"(?<!\d)(0[1-9]|1[0-2])/(\d{2}|\d{4})(?!\d)")

_CARD_DATA_TYPES = ("PAN", "CVV", "TRACK_DATA", "PIN")


@dataclass
class PrivacyReport:
    """`analyze()` çıktısı — maskeleme + kart-verisi sınıflandırması.

    - `masked_text`: standart PII + kart verisi maskelenmiş metin (dışarı gidebilir).
    - `mapping`: yalnızca RESTORE edilebilir placeholder'lar (kart verisi HARİÇ).
    - `detected_types`: bulunan kart-verisi tipleri (PAN/CVV/TRACK_DATA/PIN).
    - `blocking_findings`: doluysa canlı LLM çağrısı YAPILMAMALIDIR (SAD tespiti).
    - `risk_flags`: extraction JSON risk_flags'e birleştirilebilir sinyaller.
    """

    masked_text: str
    mapping: dict[str, str] = field(default_factory=dict)
    detected_types: set[str] = field(default_factory=set)
    blocking_findings: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


def _luhn_valid(digits: str) -> bool:
    """Kart numarası Luhn (mod-10) sağlaması."""
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def analyze(text: str) -> PrivacyReport:
    """Metni maskeler ve kart verisini sınıflandırır (§6.7 + PCI kontrol haritası).

    Sıra: standart `mask()` (restorable) → kart verisi tespiti (track → PAN →
    CVV → PIN → expiry). Kart token'ları mapping'e girmez. SAD (CVV/track/PIN)
    bulunursa `blocking_findings` doldurulur.
    """
    mr = mask(text)
    working = mr.masked_text

    detected: set[str] = set()
    blocking: list[str] = []
    risk_flags: list[str] = []
    counters: dict[str, int] = {}

    def _card_token(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return f"[[CARD_{kind}_{counters[kind]}]]"

    # 1) Track data (en spesifik) — SAD, blocking.
    def _sub_track(_match: re.Match[str]) -> str:
        detected.add("TRACK_DATA")
        return _card_token("TRACK")

    working = _TRACK1_RE.sub(_sub_track, working)
    working = _TRACK2_RE.sub(_sub_track, working)

    # 2) PAN — Luhn geçen 13-19 haneyi maskele (restore edilmez), risk flag.
    def _sub_pan(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"[ -]", "", raw)
        if not (13 <= len(digits) <= 19 and _luhn_valid(digits)):
            return raw  # Luhn'dan geçmeyen aday PAN değildir
        detected.add("PAN")
        return _card_token("PAN")

    working = _PAN_CANDIDATE_RE.sub(_sub_pan, working)

    # 3) CVV/CVC — SAD, blocking (yalnızca değer maskelenir, anahtar kelime kalır).
    def _sub_cvv(match: re.Match[str]) -> str:
        detected.add("CVV")
        return match.group(0).replace(match.group(1), _card_token("CVV"))

    working = _CVV_KW_RE.sub(_sub_cvv, working)
    working = _CVV_REV_RE.sub(_sub_cvv, working)

    # 4) PIN — SAD, blocking.
    def _sub_pin(match: re.Match[str]) -> str:
        detected.add("PIN")
        return match.group(0).replace(match.group(1), _card_token("PIN"))

    working = _PIN_RE.sub(_sub_pin, working)

    # 5) Risk flag'leri.
    if "PAN" in detected:
        risk_flags.append("PAN_DETECTED")
        if _EXPIRY_RE.search(working):
            risk_flags.append("CHD_CONTEXT")

    # 6) Blocking gerekçeleri (SAD tipleri).
    if "TRACK_DATA" in detected:
        blocking.append("Track data (manyetik şerit) tespit edildi")
    if "CVV" in detected:
        blocking.append("CVV/CVC güvenlik kodu tespit edildi")
    if "PIN" in detected:
        blocking.append("PIN tespit edildi")

    return PrivacyReport(
        masked_text=working,
        mapping=mr.mapping,
        detected_types=detected,
        blocking_findings=blocking,
        risk_flags=risk_flags,
    )
