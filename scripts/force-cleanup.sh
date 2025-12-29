#!/bin/bash
CLUSTER_NAME="podcast-transcription-fog-cluster"
REGION="us-east-1"

echo "🧹 Cleaning up ECS Cluster: $CLUSTER_NAME..."

# 1. List and Delete All Services
echo "Fetching services..."
SERVICES=$(aws ecs list-services --cluster $CLUSTER_NAME --region $REGION --query "serviceArns[]" --output text)

if [ -n "$SERVICES" ] && [ "$SERVICES" != "None" ]; then
    for SERVICE_ARN in $SERVICES; do
        SERVICE_NAME=$(basename $SERVICE_ARN)
        echo "🚨 Deleting service: $SERVICE_NAME"
        
        # Update desired count to 0 to drain tasks
        aws ecs update-service --cluster $CLUSTER_NAME --service $SERVICE_ARN --desired-count 0 --region $REGION > /dev/null
        
        # Force delete the service
        aws ecs delete-service --cluster $CLUSTER_NAME --service $SERVICE_ARN --force --region $REGION > /dev/null
        echo "   ✅ Service $SERVICE_NAME deleted."
    done
else
    echo "   ℹ️ No active services found."
fi

# 2. Stop All Running Tasks
echo "Fetching running tasks..."
TASKS=$(aws ecs list-tasks --cluster $CLUSTER_NAME --region $REGION --query "taskArns[]" --output text)

if [ -n "$TASKS" ] && [ "$TASKS" != "None" ]; then
    for TASK_ARN in $TASKS; do
        echo "� Stopping task: $TASK_ARN"
        aws ecs stop-task --cluster $CLUSTER_NAME --task $TASK_ARN --region $REGION > /dev/null
    done
    echo "   ✅ All tasks stopped."
else
    echo "   ℹ️ No running tasks found."
fi

echo "==========================================="
echo "🎉 Cleanup complete. You can now run 'terraform destroy' again."
echo "==========================================="
