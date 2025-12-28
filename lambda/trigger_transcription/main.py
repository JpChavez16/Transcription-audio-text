import json
import os
import urllib.request
import urllib.parse
import boto3


def handler(event, context):
    """
    Trigger Whisper Service when new chunk is uploaded
    """
    print("Received event:", json.dumps(event))

    # e.g. whisper-service.podcast-transcription.local
    WHISPER_Service_DNS = os.getenv("WHISPER_SERVICE_DNS")

    try:
        # 1. Parse S3 Event
        for record in event['Records']:
            s3_bucket = record['s3']['bucket']['name']
            s3_key = urllib.parse.unquote_plus(record['s3']['object']['key'])

            print(f"Processing object: {s3_key}")

            # Expected key format: audio/{job_id}/chunks/chunk_{num}.wav
            parts = s3_key.split('/')
            if len(parts) < 4 or parts[0] != "audio" or parts[2] != "chunks":
                print(f"Skipping non-chunk file: {s3_key}")
                continue

            job_id = parts[1]

            # 2. Call Whisper Service API
            # Ideally we might batched this, but for now 1:1 trigger is fine for architecture v3.0
            # S3 event-driven architecture

            url = f"http://{WHISPER_Service_DNS}:8080/transcribe"

            payload = {
                "job_id": job_id,
                "s3_keys": [s3_key],
                "model_size": "small"  # could be dynamic
            }

            data = json.dumps(payload).encode('utf-8')

            req = urllib.request.Request(
                url,
                data=data,
                headers={'Content-Type': 'application/json'}
            )

            print(f"Calling Whisper Service for job {job_id}...")
            response = urllib.request.urlopen(req)
            print("Response:", response.read().decode('utf-8'))

        return {
            'statusCode': 200,
            'body': json.dumps('Transcription triggered successfully')
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        # We don't want to retry indefinitely if it's a logic error,
        # but for network errors λ retry is good.
        raise e
