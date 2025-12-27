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

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(response["Item"], default=str)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
