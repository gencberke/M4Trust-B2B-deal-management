"""Embed chunked legal text with BGE-M3 and store it in a local Chroma collection.

    .venv/Scripts/python.exe scripts/build_rag.py

Reads every data/processed/chunks/**/*.json file (produced by
chunk_documents.py) and upserts each chunk into a persistent Chroma
collection at data/processed/embeddings/chroma/. Upsert is keyed on
chunk_id, so re-running after adding new chunks (e.g. once the 35
contract PDFs are converted and chunked) only re-embeds what changed.
"""

import json
from pathlib import Path

import chromadb
from FlagEmbedding import BGEM3FlagModel

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = ROOT / "data" / "processed" / "chunks"
CHROMA_DIR = ROOT / "data" / "processed" / "embeddings" / "chroma"
COLLECTION_NAME = "legal_articles"
BATCH_SIZE = 32


def load_all_chunks() -> list[dict]:
    chunks = []
    for path in sorted(CHUNKS_DIR.rglob("*.json")):
        chunks.extend(json.loads(path.read_text(encoding="utf-8")))
    return chunks


def build_metadata(chunk: dict) -> dict:
    meta = {"source": chunk["source"], "strategy": chunk["strategy"]}
    if "madde_no" in chunk:
        meta["madde_no"] = chunk["madde_no"]
    if "heading" in chunk:
        meta["heading"] = chunk["heading"]
    return meta


def main():
    chunks = load_all_chunks()
    if not chunks:
        print(f"No chunks found under {CHUNKS_DIR}. Run scripts/chunk_documents.py first.")
        return

    print(f"Loaded {len(chunks)} chunks. Loading BAAI/bge-m3 (first run downloads the model, ~2-3GB)...")
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        embeddings = model.encode(texts)["dense_vecs"]
        collection.upsert(
            ids=[c["chunk_id"] for c in batch],
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=[build_metadata(c) for c in batch],
        )
        print(f"  embedded {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)}")

    print(f"\nDone. Collection '{COLLECTION_NAME}' has {collection.count()} vectors at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
