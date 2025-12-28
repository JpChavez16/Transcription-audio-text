#!/bin/bash

set -e

echo "🔨 Building all components..."

# 1. Package Lambda functions
echo "📦 Packaging Lambda functions..."
mkdir -p lambda/dist

for func in url_processor query_handler; do
    echo "  → Packaging $func..."
    cd lambda/$func
    
    if [ -f requirements.txt ]; then
        pip3 install -r requirements.txt -t . --quiet
    fi
    
    zip -r ../dist/${func}.zip . -x "*.pyc" "*__pycache__*" > /dev/null
    cd ../..
done

echo "✅ Lambda functions packaged"

# 2. Build Docker images
echo "🐳 Building Docker images..."

cd docker/fog-node
docker build -t podcast-fog-node:latest . --quiet
cd ../..

echo "✅ Docker images built"

echo ""
echo "🎉 Build completed successfully!"
echo ""
echo "Next steps:"
echo "1. cd terraform"
echo "2. terraform init"
echo "3. terraform plan"
echo "4. terraform apply"