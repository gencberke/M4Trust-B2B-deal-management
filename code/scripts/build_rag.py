"""Embed chunked text with BGE-M3 and store it in local Chroma collections.

    .venv/Scripts/python.exe scripts/build_rag.py

Reads every data/processed/chunks/**/*.json file (produced by
chunk_documents.py) and upserts each chunk into one of two persistent
Chroma collections at data/processed/embeddings/chroma/, split by purpose:

- legal_articles     -- law/regulation articles, retrieved for regulatory
                         grounding when drafting a rule from a contract.
- contract_examples  -- past contract clauses, retrieved as few-shot
                         structural reference for a new contract. This is
                         retrieval-augmented context, not model training --
                         no weights change.

Kept separate because they answer different questions and mixing them
degrades retrieval quality for both. Upsert is keyed on chunk_id, so
re-running after adding new chunks only re-embeds what changed.
"""

import json
from pathlib import Path

import chromadb
from FlagEmbedding import BGEM3FlagModel

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = ROOT / "data" / "processed" / "chunks"
CHROMA_DIR = ROOT / "data" / "processed" / "embeddings" / "chroma"
BATCH_SIZE = 32


def load_chunks_by_collection() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {"legal_articles": [], "contract_examples": []}
    for path in sorted(CHUNKS_DIR.rglob("*.json")):
        rel = path.relative_to(CHUNKS_DIR)
        collection = "contract_examples" if rel.parts[0] == "contracts" else "legal_articles"
        grouped[collection].extend(json.loads(path.read_text(encoding="utf-8")))
    return grouped


def build_metadata(chunk: dict) -> dict:
    meta = {"source": chunk["source"], "strategy": chunk["strategy"]}
    if "madde_no" in chunk:
        meta["madde_no"] = chunk["madde_no"]
    if "heading" in chunk:
        meta["heading"] = chunk["heading"]
    return meta


def embed_collection(client, model, name: str, chunks: list[dict]) -> None:
    if not chunks:
        print(f"  ({name}: no chunks, skipping)")
        return

    collection = client.get_or_create_collection(name)
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
        print(f"  [{name}] embedded {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)}")

    print(f"  [{name}] done: {collection.count()} vectors total")


def main():
    grouped = load_chunks_by_collection()
    total = sum(len(v) for v in grouped.values())
    if total == 0:
        print(f"No chunks found under {CHUNKS_DIR}. Run scripts/chunk_documents.py first.")
        return

    print(f"Loaded {total} chunks. Loading BAAI/bge-m3 (first run downloads the model, ~2-3GB)...")
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    for name, chunks in grouped.items():
        embed_collection(client, model, name, chunks)

    print(f"\nAll done. Collections stored at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
