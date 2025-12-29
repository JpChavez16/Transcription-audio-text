#!/bin/bash
set -e

# Configuration
REGION="us-east-1"
PROJECT_NAME="podcast-transcription"

echo "🚀 Starting Deployment Process..."

# 1. Get Infrastructure Details
echo "🔍 Fetching infrastructure details from Terraform..."
cd ../terraform
FOG_REPO=$(terraform output -raw fog_node_ecr_url)
WHISPER_REPO=$(terraform output -raw whisper_service_ecr_url)

CLUSTER_NAME=$(terraform output -raw ecs_cluster_name)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "   Fog Repo: $FOG_REPO"
echo "   Whisper Repo: $WHISPER_REPO"
echo "   Cluster: $CLUSTER_NAME"


# 2. Build & Push Docker Images
echo "🐳 Logging into ECR..."
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

echo "🔨 Building & Pushing Fog Node..."
cd ../docker/fog-node
docker build --no-cache -t "$FOG_REPO:latest" . --quiet
docker push "$FOG_REPO:latest"

echo "🔨 Building & Pushing Whisper Service..."
cd ../whisper-service
docker build -t "$WHISPER_REPO:latest" . --quiet
docker push "$WHISPER_REPO:latest"

# 3. Connect ECS to new images
echo "🔄 Forcing ECS Service Deployments..."
aws ecs update-service --cluster "$CLUSTER_NAME" --service "${PROJECT_NAME}-fog-nodes" --force-new-deployment > /dev/null
echo "   Updated Fog Nodes"

aws ecs update-service --cluster "$CLUSTER_NAME" --service "${PROJECT_NAME}-whisper-service" --force-new-deployment > /dev/null
echo "   Updated Whisper Service"

echo "✅ DEPLOYMENT COMPLETE!"
echo ""
echo "You can now run ./test-submission.sh to verify the system."
