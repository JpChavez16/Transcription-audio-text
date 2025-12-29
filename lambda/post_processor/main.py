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

def get_job_metadata(job_id: str) -> dict:
    """Fetch job metadata from DynamoDB to get total_chunks"""
    table = dynamodb.Table(os.environ["JOBS_TABLE"])
    response = table.get_item(Key={"jobId": job_id})
    return response.get("Item", {})

def list_chunk_files(bucket: str, prefix: str) -> List[str]:
    """List all JSON chunk files in S3"""
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
    # Ensure numerical sorting if chunk names like chunk_001.json
    # They should already be sorted by S3 string sort, but being explicit is safer if needed.
    # For now, string sort of "chunk_000.json" works perfectly.
    
    print(f"Merging {len(chunk_keys)} chunks...")
    for key in chunk_keys:
        try:
            text = read_chunk(bucket, key)
            if text:
                texts.append(text.strip())
        except Exception as e:
            print(f"Error reading chunk {key}: {e}")
            
    return " ".join(texts)

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

def update_job_status(job_id: str, status: str, output_key: str):
    table = dynamodb.Table(os.environ["JOBS_TABLE"])
    timestamp = datetime.utcnow().isoformat()
    
    table.update_item(
        Key={"jobId": job_id},
        UpdateExpression="SET #s = :status, updatedAt = :t, transcriptionKey = :k",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": status,
            ":t": timestamp,
            ":k": output_key
        }
    )

def extract_job_id_from_s3_event(event) -> str:
    try:
        # Key format: transcriptions/{job_id}/chunks/chunk_XXX.json
        key = event["Records"][0]["s3"]["object"]["key"]
        parts = key.split("/")
        if len(parts) > 1:
            return parts[1]
    except Exception as e:
        print(f"Error extracting job_id: {e}")
    return None

# =========================
# LAMBDA HANDLER
# =========================

def handler(event, context):
    print("Received S3 Event")
    
    job_id = extract_job_id_from_s3_event(event)
    if not job_id:
        print("Could not extract job_id from event")
        return {"statusCode": 400, "body": "Invalid event structure"}

    print(f"Processing Job ID: {job_id}")

    # 1. Get Expected Total Chunks
    job_data = get_job_metadata(job_id)
    if not job_data:
        print("Job not found in DynamoDB")
        return {"statusCode": 404, "body": "Job not found"}
    
    expected_chunks = int(job_data.get("totalChunks", 0))
    if expected_chunks == 0:
        print("Job has 0 totalChunks, cannot verify completion. Exiting.")
        return {"statusCode": 200, "body": "No chunks expected"}

    # 2. Count Encoded Chunks in S3
    chunks_prefix = f"transcriptions/{job_id}/chunks/"
    found_chunks = list_chunk_files(TRANSCRIPTIONS_BUCKET, chunks_prefix)
    current_count = len(found_chunks)
    
    print(f"Progress: {current_count}/{expected_chunks} chunks")

    # 3. Check Condition
    if current_count < expected_chunks:
        print("Job not yet complete. Waiting for more chunks.")
        return {"statusCode": 200, "body": "Job in progress"}
    
    if current_count > expected_chunks:
        print("Warning: More chunks found than expected. Proceeding with merge anyway.")

    # 4. Correctness Check - Wait for stability? 
    # S3 eventual consistency is technically read-after-write consistent for new objects, 
    # but list consistency is what matters here. list_objects_v2 is strongly consistent since Dec 2020.
    
    # 5. Perform Merge
    print("All chunks present. Starting merge...")
    full_text = merge_chunks(TRANSCRIPTIONS_BUCKET, found_chunks)
    
    # 6. Save Outputs
    base_key = f"transcriptions/{job_id}"
    
    # Text File
    upload_text(TRANSCRIPTIONS_BUCKET, f"{base_key}/transcription.txt", full_text)
    
    # JSON Metadata
    upload_json(TRANSCRIPTIONS_BUCKET, f"{base_key}/transcription.json", {
        "jobId": job_id,
        "text": full_text,
        "chunks": len(found_chunks),
        "completedAt": datetime.utcnow().isoformat()
    })
    
    # 7. Update DynamoDB
    update_job_status(job_id, "completed", f"{base_key}/transcription.json")
    
    print("Job completed successfully!")
    return {"statusCode": 200, "body": "Job completed"}

