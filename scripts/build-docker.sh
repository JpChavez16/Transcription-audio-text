#!/bin/bash

echo "🐳 Building Docker images..."

cd docker/fog-node
docker build -t podcast-fog-node:latest .

cd ../whisper-service
docker build -t podcast-whisper:latest .

cd ../..

echo "✅ Docker images built successfully"
