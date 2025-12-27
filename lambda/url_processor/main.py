"""
URL Processor Lambda - Usa Service Discovery en lugar de ALB
"""
import json
import os
import boto3
import uuid
from datetime import datetime
import urllib3

dynamodb = boto3.resource("dynamodb")
ecs_client = boto3.client("ecs")
table = dynamodb.Table(os.getenv("JOBS_TABLE"))

# HTTP client
http = urllib3.PoolManager()

FOG_NODES_DNS = os.getenv("FOG_NODES_DNS")  # fog-nodes.podcast-transcription.local
ECS_CLUSTER = os.getenv("ECS_CLUSTER_NAME")
ECS_SERVICE = os.getenv("ECS_SERVICE_NAME")

def handler(event, context):
    """
    Process incoming URL submission
    """
    try:
        # Parse request body
        body = json.loads(event.get("body", "{}"))
        
        url = body.get("url")
        user_id = body.get("userId", "anonymous")
        model_size = body.get("modelSize", "medium")
        
        if not url:
            return error_response(400, "URL is required")
        
        # Validate URL
        if not is_valid_url(url):
            return error_response(400, "Invalid URL format")
        
        # Create job
        job_id = str(uuid.uuid4())
        created_at = int(datetime.utcnow().timestamp())
        
        job_data = {
            "jobId": job_id,
            "createdAt": created_at,
            "userId": user_id,
            "url": url,
            "status": "pending",
            "progress": 0,
            "message": "Job created, routing to fog node",
            "modelSize": model_size,
            "ttl": created_at + (30 * 24 * 60 * 60)  # 30 days
        }
        
        # Save to DynamoDB
        table.put_item(Item=job_data)
        
        print(f"Created job {job_id} for URL: {url}")
        
        # Route to fog node via Service Discovery
        try:
            fog_response = route_to_fog_node(job_id, url, model_size)
            print(f"Fog node response: {fog_response}")
        except Exception as e:
            print(f"Warning: Could not route to fog node immediately: {e}")
            # Job is still created, can be processed later
        
        return success_response({
            "jobId": job_id,
            "status": "pending",
            "message": "Job submitted successfully - streaming mode",
            "estimatedTime": "10-15 minutes",
            "processing_method": "streaming_no_download"
        })
        
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return error_response(500, f"Internal server error: {str(e)}")

def is_valid_url(url: str) -> bool:
    """Validate URL format"""
    try:
        from urllib.parse import urlparse
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def route_to_fog_node(job_id: str, url: str, model_size: str) -> dict:
    """
    Route job to fog node using Service Discovery DNS
    """
    try:
        # Usar Service Discovery DNS
        fog_url = f"http://{FOG_NODES_DNS}:8080/process"
        
        payload = json.dumps({
            "url": url,
            "job_id": job_id,
            "model_size": model_size
        })
        
        response = http.request(
            "POST",
            fog_url,
            body=payload,
            headers={"Content-Type": "application/json"},
            timeout=10.0
        )
        
        return json.loads(response.data.decode("utf-8"))
        
    except Exception as e:
        print(f"Failed to route to fog node: {e}")
        # Return success anyway - job can be picked up by polling
        return {"status": "queued", "message": "Will be processed"}

def get_fog_node_ip() -> str:
    """
    Get IP of a running fog node task (fallback method)
    """
    try:
        # List tasks in the service
        response = ecs_client.list_tasks(
            cluster=ECS_CLUSTER,
            serviceName=ECS_SERVICE,
            desiredStatus="RUNNING"
        )
        
        if not response.get("taskArns"):
            raise Exception("No running fog node tasks found")
        
        # Describe first task to get IP
        task_arn = response["taskArns"][0]
        task_details = ecs_client.describe_tasks(
            cluster=ECS_CLUSTER,
            tasks=[task_arn]
        )
        
        # Get private IP from ENI
        for attachment in task_details["tasks"][0]["attachments"]:
            for detail in attachment.get("details", []):
                if detail.get("name") == "privateIPv4Address":
                    return detail.get("value")
        
        raise Exception("Could not find task IP")
        
    except Exception as e:
        print(f"Error getting fog node IP: {e}")
        return None

def success_response(data: dict, status_code: int = 200):
    """Generate success response"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": True
        },
        "body": json.dumps(data)
    }

def error_response(status_code: int, message: str):
    """Generate error response"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": True
        },
        "body": json.dumps({
            "error": message
        })
    }