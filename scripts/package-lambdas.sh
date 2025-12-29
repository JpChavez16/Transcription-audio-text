#!/bin/bash

echo "📦 Packaging Lambda functions..."

mkdir -p lambda/dist

for func in query_handler; do
    echo "Packaging $func..."
    cd lambda/$func

    if [ -f requirements.txt ]; then
        pip install -r requirements.txt -t .
    fi

    zip -r ../dist/${func}.zip . -x "*.pyc" "*__pycache__*"
    cd ../..
done

echo "✅ Lambda functions packaged"
