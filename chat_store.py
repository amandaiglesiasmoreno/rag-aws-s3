"""Chat history stored in Amazon S3 (replaces the chat_history table).

One JSON object per conversation:  s3://<bucket>/chat-history/<session_id>.json
An S3 Lifecycle rule deletes objects 7 days after their last update
(replaces the old asyncio TTL cleanup task).
"""
import json
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from config import AWS_REGION, S3_BUCKET, S3_HISTORY_PREFIX

s3 = boto3.client("s3", region_name=AWS_REGION)
_SESSION_RE = re.compile(r"^[a-f0-9]{32}$")


def is_valid_session_id(session_id: str) -> bool:
    # Prevents arbitrary S3 keys being built from URL parameters
    return bool(_SESSION_RE.match(session_id or ""))


def _key(session_id: str) -> str:
    if not is_valid_session_id(session_id):
        raise ValueError("Invalid session id")
    return f"{S3_HISTORY_PREFIX}{session_id}.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_history(session_id: str) -> list[dict]:
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=_key(session_id))
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return []  # new conversation
        raise
    return json.loads(obj["Body"].read()).get("messages", [])


def save_history(session_id: str, messages: list[dict]) -> None:
    body = {"session_id": session_id, "updated_at": now_iso(), "messages": messages}
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=_key(session_id),
        Body=json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def delete_history(session_id: str) -> None:
    s3.delete_object(Bucket=S3_BUCKET, Key=_key(session_id))
