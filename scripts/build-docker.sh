#!/bin/bash

echo "🐳 Building Docker images..."

# Get absolute path to project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🐳 Building Docker images..."

cd "$PROJECT_ROOT/docker/fog-node"
docker build -t podcast-fog-node:latest .

cd "$PROJECT_ROOT/docker/whisper-service"
docker build -t podcast-whisper:latest .

echo "✅ Docker images built successfully"

echo "ℹ️  To push to ECR:"
echo "   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin \$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com"
echo "   docker tag podcast-fog-node:latest \$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/podcast-transcription-fog-node:latest"
echo "   docker push \$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/podcast-transcription-fog-node:latest"
echo "   docker tag podcast-whisper:latest \$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/podcast-transcription-whisper-service:latest"
echo "   docker push \$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/podcast-transcription-whisper-service:latest"
