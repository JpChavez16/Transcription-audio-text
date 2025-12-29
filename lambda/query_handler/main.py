import json
import os
import boto3

dynamodb = boto3.resource("dynamodb")
jobs_table = dynamodb.Table(os.getenv("JOBS_TABLE", "jobs"))

def handler(event, context):
    try:
        job_id = event["pathParameters"]["jobId"]

        response = jobs_table.get_item(Key={"jobId": job_id})

        if "Item" not in response:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Job not found"})
            }

        item = response["Item"]

        # If job is completed, generate presigned URLs for the artifacts
        if item.get("status") == "completed":
            try:
                s3_client = boto3.client('s3')
                bucket = os.environ.get("TRANSCRIPTIONS_BUCKET")
                
                # We assume the keys based on the standard naming convention
                # transcriptions/{job_id}/transcription.json
                # transcriptions/{job_id}/transcription.txt
                
                if bucket:
                    # Generate Presigned URL for JSON
                    json_key = f"transcriptions/{job_id}/transcription.json"
                    item["downloadUrlJson"] = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': bucket, 'Key': json_key},
                        ExpiresIn=3600
                    )
                    
                    # Generate Presigned URL for TXT
                    txt_key = f"transcriptions/{job_id}/transcription.txt"
                    item["downloadUrlTxt"] = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': bucket, 'Key': txt_key},
                        ExpiresIn=3600
                    )
            except Exception as e:
                print(f"Error generating presigned URLs: {e}")

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(item, default=str)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
