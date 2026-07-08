"""Convert a single uploaded PDF/DOCX file into clean markdown text.

    python scripts/convert_documents.py path/to/sozlesme.pdf

Runtime counterpart to chunk_documents.py/build_rag.py: those two prepare the
one-time legal/contract corpus, this one runs per uploaded contract at
request time. It only parses -- chunking/embedding a live contract, if ever
needed, is a separate step downstream.
"""

import argparse
import logging
import sys
from pathlib import Path

from document_parser import DocumentConverter, DocumentParserError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# On Windows, stdout defaults to the system codepage rather than UTF-8 when
# not attached to a terminal (e.g. redirected to a file), which silently
# mangles Turkish characters. Force UTF-8 so converted text round-trips.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_path", type=Path, help="PDF or DOCX file to convert")
    args = parser.parse_args()

    try:
        text = DocumentConverter().convert(args.file_path)
    except DocumentParserError as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(text)


if __name__ == "__main__":
    main()
