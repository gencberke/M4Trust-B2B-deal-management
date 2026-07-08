"""Split converted markdown files into retrievable chunks.

    python scripts/chunk_documents.py

Legal texts written as numbered articles (6098, 6493, 5549 ...) are split
one chunk per "**MADDE N**" marker. Documents that aren't structured that
way (e.g. the KVKK uygulama rehberi, which is prose organized by headings
rather than articles) fall back to splitting on markdown headings, so
nothing is silently skipped.

data/processed/markdown/legal/6098kk.md -> data/processed/chunks/legal/6098kk.json
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_DIR = ROOT / "data" / "processed" / "markdown"
CHUNKS_DIR = ROOT / "data" / "processed" / "chunks"

# Matches bold article markers: **MADDE 1-**, **MADDE 1 – (1)**, amended
# articles like **MADDE 9- (Değişik:2/3/2024-7499/34 md.)**, and lettered
# "ek madde" insertions like **MADDE 9/A- (Ek: 18/6/2014-6545/87 md.)** --
# the /A suffix is captured too, since 9 and 9/A are different articles.
MADDE_RE = re.compile(r"\*\*\s*MADDE\s+(\d+(?:/[A-ZÇĞİÖŞÜ])?)[^*\n]{0,120}\*\*", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
PAGE_MARKER_RE = re.compile(r"\{\d+\}-+\s*")
# A run of markdown headings trailing at the very end of a slice belongs to
# the *next* article/section, not the one being closed out here.
TRAILING_HEADING_RE = re.compile(r"(?:\n+#{1,6}[^\n]*)+\Z")

MIN_HEADING_CHUNK_LEN = 40  # skip near-empty sections (cover pages, logos, etc.)


def clean(text: str) -> str:
    text = PAGE_MARKER_RE.sub("", text).strip()
    text = TRAILING_HEADING_RE.sub("", text).strip()
    return text


def chunk_by_madde(markdown: str, source: str) -> list[dict]:
    matches = list(MADDE_RE.finditer(markdown))
    chunks = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = clean(markdown[start:end])
        if not body:
            continue
        madde_no = m.group(1)  # e.g. "9" or "9/A", kept as a string
        chunks.append(
            {
                "source": source,
                "strategy": "madde",
                "madde_no": madde_no,
                # Sequential index, not madde_no: some documents embed multiple
                # regulations that each restart their own numbering at MADDE 1,
                # so madde_no alone is not unique within a file.
                "chunk_id": f"{source}#{i:03d}-madde-{madde_no.replace('/', '-')}",
                "text": f"MADDE {madde_no} - {body}",
            }
        )
    return chunks


def chunk_by_heading(markdown: str, source: str) -> list[dict]:
    matches = list(HEADING_RE.finditer(markdown))
    chunks = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = clean(markdown[start:end])
        if len(body) < MIN_HEADING_CHUNK_LEN:
            continue
        title = m.group(2).strip()
        chunks.append(
            {
                "source": source,
                "strategy": "heading",
                "heading": title,
                "chunk_id": f"{source}#heading-{i}",
                "text": f"{title}\n{body}",
            }
        )
    return chunks


def chunk_file(md_path: Path) -> list[dict]:
    source = md_path.stem
    markdown = md_path.read_text(encoding="utf-8")
    chunks = chunk_by_madde(markdown, source)
    if chunks:
        return chunks
    return chunk_by_heading(markdown, source)


def main():
    md_files = sorted(MARKDOWN_DIR.rglob("*.md"))
    if not md_files:
        print(f"No markdown files found under {MARKDOWN_DIR}")
        return

    total_chunks = 0
    for md_path in md_files:
        rel = md_path.relative_to(MARKDOWN_DIR)
        chunks = chunk_file(md_path)
        out_path = (CHUNKS_DIR / rel).with_suffix(".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

        strategy = chunks[0]["strategy"] if chunks else "none"
        print(f"{rel}: {len(chunks)} chunks ({strategy})")
        total_chunks += len(chunks)

    print(f"\nTotal: {total_chunks} chunks across {len(md_files)} files -> {CHUNKS_DIR}")


if __name__ == "__main__":
    main()
