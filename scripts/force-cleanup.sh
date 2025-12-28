#!/bin/bash

# Configuration
PROJECT_NAME="podcast-transcription"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"

echo "🧹 Force Cleaning Orphaned Resources..."

# 1. Delete ECR Repositories
REPOS="$PROJECT_NAME-fog-node $PROJECT_NAME-whisper-service"
for repo in $REPOS; do
    echo "   Checking ECR repo: $repo"
    if aws ecr describe-repositories --repository-names $repo --region $REGION >/dev/null 2>&1; then
        echo "   🗑️  Deleting ECR repo: $repo"
        aws ecr delete-repository --repository-name $repo --region $REGION --force >/dev/null
    else
        echo "   - Not found, skipping."
    fi
done

# 2. Delete Web Bucket
WEB_BUCKET="$PROJECT_NAME-web-$ACCOUNT_ID"
echo "   Checking S3 bucket: $WEB_BUCKET"
if aws s3 ls "s3://$WEB_BUCKET" 2>&1 | grep -q 'NoSuchBucket'; then
     echo "   - Not found, skipping."
else
    echo "   🗑️  Deleting bucket: $WEB_BUCKET"
    aws s3 rb "s3://$WEB_BUCKET" --force >/dev/null
fi

# 3. Clean Terraform State (crucial since we just confused it)
echo "   Refresh Terraform State..."
cd ../terraform
terraform refresh

echo "✅ Clean up complete."
