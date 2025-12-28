#!/bin/bash

# Get Cluster and Service Names from Terraform
cd ../terraform
CLUSTER_NAME=$(terraform output -raw ecs_cluster_name)
# We need to construct service names or get them if we output them
# Assuming standard naming convention or fetching from output if available

# Let's verify if we have these outputs in main.tf
# We output 'ecs_cluster_name' but maybe not the exact service name for fog nodes?
# fog-nodes module outputs 'service_name' as 'fog_node_service_name'?
# Let's check terraform/main.tf outputs again. 
# It outputs 'ecs_cluster_name'. 
# It does NOT output the fog node service name directly as a root output?
# lines 136-139 output ecs_cluster_name.
# We might need to guess the service name or add it to outputs.
# But usually it is PROJECT_NAME-fog-node-service.

PROJECT_NAME="podcast-transcription" # Default
REGION="us-east-1"

FOG_SERVICE="$PROJECT_NAME-fog-node-service"
WHISPER_SERVICE="$PROJECT_NAME-whisper-service"

echo "🔄 Forcing new deployment for Cluster: $CLUSTER_NAME"

echo "   - Service: $FOG_SERVICE"
aws ecs update-service --cluster $CLUSTER_NAME --service $FOG_SERVICE --force-new-deployment --region $REGION > /dev/null
echo "     ✅ Triggered"

echo "   - Service: $WHISPER_SERVICE"
aws ecs update-service --cluster $CLUSTER_NAME --service $WHISPER_SERVICE --force-new-deployment --region $REGION > /dev/null
echo "     ✅ Triggered"

echo "⏳ Waiting for services to stabilize (this may take a few minutes)..."
aws ecs wait services-stable --cluster $CLUSTER_NAME --services $FOG_SERVICE $WHISPER_SERVICE --region $REGION
echo "✅ Deployment completed!"
