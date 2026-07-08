"""Cleans raw extractor output into consistent markdown text."""

import re
import unicodedata

# 3+ consecutive newlines collapse to a single paragraph break.
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
# Runs of horizontal whitespace (spaces/tabs) collapse to one space.
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
# Control/formatting characters (incl. BOM) that extractors and OCR leave behind.
_CONTROL_CHARS_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f" + chr(0xFEFF) + "]")


class MarkdownNormalizer:
    """Normalizes extractor output into clean, consistent markdown text."""

    def normalize(self, text: str) -> str:
        text = unicodedata.normalize("NFC", text)
        text = _CONTROL_CHARS_RE.sub("", text)
        text = "\n".join(line.strip() for line in text.splitlines())
        text = _MULTI_SPACE_RE.sub(" ", text)
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        return text.strip()
