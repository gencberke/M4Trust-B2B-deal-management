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
