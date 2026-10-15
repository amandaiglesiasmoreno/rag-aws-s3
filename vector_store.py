"""Amazon S3 Vectors as the vector database (replaces Render PostgreSQL + pgvector).

Each chunk is stored as one vector:
  key      = "<source>#<chunk_index>"
  data     = OpenAI embedding (float32, EMBEDDING_DIM dims)
  metadata = {"source": ..., "chunk_index": ..., "content": ...}
"content" is declared non-filterable so long text fits the metadata limits.
"""
from collections import Counter

import boto3
from botocore.exceptions import ClientError

from config import AWS_REGION, EMBEDDING_DIM, VECTOR_BUCKET, VECTOR_INDEX

s3v = boto3.client("s3vectors", region_name=AWS_REGION)
PUT_BATCH = 500  # max vectors per PutVectors call


def _is_conflict(e: ClientError) -> bool:
    return e.response["Error"]["Code"] in ("ConflictException", "AlreadyExists")


def _is_not_found(e: ClientError) -> bool:
    return e.response["Error"]["Code"] in ("NotFoundException", "NoSuchIndex", "ResourceNotFoundException")


def ensure_bucket_and_index() -> None:
    """Create the vector bucket and index if they don't exist (idempotent)."""
    try:
        s3v.create_vector_bucket(vectorBucketName=VECTOR_BUCKET)
    except ClientError as e:
        if not _is_conflict(e):
            raise
    try:
        s3v.create_index(
            vectorBucketName=VECTOR_BUCKET,
            indexName=VECTOR_INDEX,
            dataType="float32",
            dimension=EMBEDDING_DIM,
            distanceMetric="cosine",
            metadataConfiguration={"nonFilterableMetadataKeys": ["content"]},
        )
    except ClientError as e:
        if not _is_conflict(e):
            raise


def reset_index() -> None:
    """Full re-index: delete and recreate the index (equivalent of TRUNCATE)."""
    try:
        s3v.delete_index(vectorBucketName=VECTOR_BUCKET, indexName=VECTOR_INDEX)
    except ClientError as e:
        if not _is_not_found(e):
            raise
    ensure_bucket_and_index()


def put_chunks(rows: list[tuple[str, int, str, list[float]]]) -> None:
    """rows = [(source, chunk_index, content, embedding), ...]"""
    vectors = [
        {
            "key": f"{source}#{idx}",
            "data": {"float32": [float(x) for x in emb]},
            "metadata": {"source": source, "chunk_index": idx, "content": content},
        }
        for source, idx, content, emb in rows
    ]
    for i in range(0, len(vectors), PUT_BATCH):
        s3v.put_vectors(
            vectorBucketName=VECTOR_BUCKET, indexName=VECTOR_INDEX, vectors=vectors[i : i + PUT_BATCH]
        )


def query(embedding: list[float], k: int) -> list[dict]:
    resp = s3v.query_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=VECTOR_INDEX,
        queryVector={"float32": [float(x) for x in embedding]},
        topK=k,
        returnDistance=True,
        returnMetadata=True,
    )
    results = []
    for v in resp.get("vectors", []):
        md = v.get("metadata", {}) or {}
        results.append(
            {
                "source": md.get("source", v["key"].rsplit("#", 1)[0]),
                "chunk_index": int(md.get("chunk_index", 0)),
                "content": md.get("content", ""),
                "distance": float(v.get("distance", 0.0)),
            }
        )
    return sorted(results, key=lambda r: r["distance"])


def count_chunks_by_source() -> list[tuple[str, int]]:
    """Counts chunks per source from the vector keys (no metadata needed)."""
    counts: Counter = Counter()
    kwargs = {"vectorBucketName": VECTOR_BUCKET, "indexName": VECTOR_INDEX, "maxResults": 1000}
    try:
        while True:
            resp = s3v.list_vectors(**kwargs)
            for v in resp.get("vectors", []):
                counts[v["key"].rsplit("#", 1)[0]] += 1
            if not resp.get("nextToken"):
                break
            kwargs["nextToken"] = resp["nextToken"]
    except ClientError as e:
        if _is_not_found(e):
            return []
        raise
    return sorted(counts.items())
