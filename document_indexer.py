"""Index documents into Amazon S3 Vectors using OpenAI embeddings.

Sources: local ./docs folder (default) or s3://S3_BUCKET/<S3_DOCS_PREFIX> (e.g. "docs/").
Run: python document_indexer.py
"""
import io
import os

import boto3
from openai import OpenAI
from pypdf import PdfReader

import vector_store
from config import AWS_REGION, EMBEDDING_MODEL, OPENAI_API_KEY, S3_BUCKET, S3_DOCS_PREFIX

DOCS_PATH = "./docs"
client = OpenAI(api_key=OPENAI_API_KEY)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    """Fixed-size chunks with overlap; tries to end chunks at a sentence boundary."""
    text = " ".join(text.split())
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            cut = text.rfind(". ", start, end)
            if cut > start + chunk_size // 2:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def parse_file(filename: str, data: bytes) -> str | None:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if filename.lower().endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")
    return None


def load_local_documents() -> list[tuple[str, str]]:
    if not os.path.exists(DOCS_PATH):
        os.makedirs(DOCS_PATH)
        print(f"Created {DOCS_PATH} - put your PDF/TXT/MD files there and run again.")
        return []
    docs = []
    for filename in sorted(os.listdir(DOCS_PATH)):
        with open(os.path.join(DOCS_PATH, filename), "rb") as f:
            text = parse_file(filename, f.read())
        if text:
            docs.append((filename, text))
    return docs


def load_s3_documents() -> list[tuple[str, str]]:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    docs = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=S3_BUCKET, Prefix=S3_DOCS_PREFIX):
        for obj in page.get("Contents", []):
            filename = obj["Key"].rsplit("/", 1)[-1]
            if not filename:
                continue
            text = parse_file(filename, s3.get_object(Bucket=S3_BUCKET, Key=obj["Key"])["Body"].read())
            if text:
                docs.append((filename, text))
    return docs


def embed_batch(texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in response.data]


def main():
    documents = load_s3_documents() if S3_DOCS_PREFIX else load_local_documents()
    print(f"Loaded {len(documents)} documents from {'S3' if S3_DOCS_PREFIX else DOCS_PATH}.")

    rows = []
    for filename, text in documents:
        chunks = chunk_text(text)
        for start in range(0, len(chunks), 100):
            batch = chunks[start : start + 100]
            for offset, (chunk, emb) in enumerate(zip(batch, embed_batch(batch))):
                rows.append((filename, start + offset, chunk, emb))
        print(f"  {filename}: {len(chunks)} chunks")

    # Full re-index: recreate the index so re-runs don't leave stale chunks
    vector_store.reset_index()
    vector_store.put_chunks(rows)
    print(f"Indexed {len(rows)} chunks from {len(documents)} documents into S3 Vectors.")


if __name__ == "__main__":
    main()
