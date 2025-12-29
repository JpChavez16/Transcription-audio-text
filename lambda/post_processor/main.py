import json
import os
import boto3
from datetime import datetime
from typing import List

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# =========================
# ENV VARS
# =========================
TRANSCRIPTIONS_TABLE = os.environ.get(
    "TRANSCRIPTIONS_TABLE", "podcast-transcription-transcriptions"
)

TRANSCRIPTIONS_BUCKET = os.environ.get(
    "TRANSCRIPTIONS_BUCKET"
)

CHUNKS_PREFIX = os.environ.get(
    "CHUNKS_PREFIX", "chunks"
)

OUTPUT_PREFIX = os.environ.get(
    "OUTPUT_PREFIX", "transcriptions"
)

# =========================
# UTILS
# =========================

def list_chunk_files(bucket: str, prefix: str) -> List[str]:
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    keys = []
    for page in pages:
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".json"):
                keys.append(obj["Key"])

    return sorted(keys)


def read_chunk(bucket: str, key: str) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)
    data = json.loads(obj["Body"].read())
    return data.get("text", "")


def merge_chunks(bucket: str, chunk_keys: List[str]) -> str:
    texts = []
    for key in chunk_keys:
        text = read_chunk(bucket, key)
        if text:
            texts.append(text.strip())
    return "\n".join(texts)


def generate_simple_summary(text: str, max_sentences: int = 3) -> str:
    """
    Extractive summary:
    Toma las primeras N frases del texto.
    """
    sentences = [
        s.strip()
        for s in text.replace("\n", " ").split(".")
        if len(s.strip()) > 20
    ]

    summary = ". ".join(sentences[:max_sentences])
    if summary:
        summary += "."
    return summary

def extract_job_id_from_s3_event(event) -> str:
    """
    Extrae job_id desde la key del objeto S3.
    Espera formato:
    transcriptions/<job_id>/chunks/chunk_xxx.json
    """
    try:
        record = event["Records"][0]
        key = record["s3"]["object"]["key"]
        parts = key.split("/")
        return parts[1]
    except Exception:
        return None



def upload_text(bucket: str, key: str, content: str):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain"
    )


def upload_json(bucket: str, key: str, payload: dict):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2).encode("utf-8"),
        ContentType="application/json"
    )


def update_dynamo(job_id: str, summary: str):
    table = dynamodb.Table(TRANSCRIPTIONS_TABLE)

    table.update_item(
        Key={"transcriptionId": job_id},
        UpdateExpression="""
            SET #st = :status,
                summary = :summary,
                summaryMethod = :method,
                updatedAt = :updated
        """,
        ExpressionAttributeNames={
            "#st": "status"
        },
        ExpressionAttributeValues={
            ":status": "completed",
            ":summary": summary,
            ":method": "extractive",
            ":updated": datetime.utcnow().isoformat()
        }
    )


# =========================
# LAMBDA HANDLER
# =========================

def handler(event, context):
    print("📥 Event received:", json.dumps(event))

    # ⚠️ Ajusta esto si tu job_id llega de otra forma
    job_id = extract_job_id_from_s3_event(event)
    if not job_id:
        raise ValueError("job_id not found in S3 object key")


    chunks_prefix = f"{OUTPUT_PREFIX}/{job_id}/{CHUNKS_PREFIX}/"

    print(f"🔎 Listing chunks in {chunks_prefix}")
    chunk_keys = list_chunk_files(TRANSCRIPTIONS_BUCKET, chunks_prefix)

    if not chunk_keys:
        raise RuntimeError("No chunk files found")

    print(f"🧩 {len(chunk_keys)} chunks found")

    full_text = merge_chunks(TRANSCRIPTIONS_BUCKET, chunk_keys)
    summary = generate_simple_summary(full_text)

    timestamp = datetime.utcnow().isoformat()

    base_output = f"{OUTPUT_PREFIX}/{job_id}"

    upload_text(
        TRANSCRIPTIONS_BUCKET,
        f"{base_output}/transcription.txt",
        full_text
    )

    upload_text(
        TRANSCRIPTIONS_BUCKET,
        f"{base_output}/summary.txt",
        summary
    )

    upload_json(
        TRANSCRIPTIONS_BUCKET,
        f"{base_output}/transcription.json",
        {
            "job_id": job_id,
            "text": full_text,
            "summary": summary,
            "summaryMethod": "extractive",
            "createdAt": timestamp
        }
    )

    update_dynamo(job_id, summary)

    print("✅ Post-processing completed")

    return {
        "statusCode": 200,
        "body": {
            "job_id": job_id,
            "status": "completed",
            "summary": summary
        }
    }
