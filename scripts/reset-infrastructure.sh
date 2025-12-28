#!/bin/bash
set -e

echo "⚠️  WARNING: This script will DESTROY all resources and DELETE all data in S3."
echo "    It will then re-provision the infrastructure."
echo "    Press Ctrl+C within 5 seconds to cancel..."
sleep 5

PROJECT_NAME="podcast-transcription"

# 1. Empty Buckets to prevent Terraform hang
echo "🧹 Finding and Emptying S3 Buckets..."
# Get all buckets for this project
BUCKETS=$(aws s3 ls | grep "$PROJECT_NAME" | awk '{print $3}')

if [ -n "$BUCKETS" ]; then
    for bucket in $BUCKETS; do
        echo "   🗑️  Emptying $bucket..."
        # Use --quiet to reduce noise, run in parallel if possible but sequential is safer
        aws s3 rm "s3://$bucket" --recursive --quiet
    done
    echo "✅ Buckets emptied."
else
    echo "   ℹ️  No buckets found to empty."
fi

# 2. Terraform Destroy
echo "💥 Destroying Infrastructure..."
cd ../terraform
terraform destroy -auto-approve

# 3. Clean local state (optional but good for a "hard" reset if state is corrupted)
# rm -rf .terraform
# rm -f .terraform.lock.hcl
# terraform init

# 4. Terraform Apply
echo "🏗️  Re-Creating Infrastructure..."
terraform apply -auto-approve

# 5. Output Info
echo "✅ Infrastructure Reset Complete!"
API_URL=$(terraform output -raw api_gateway_url)
echo "   API URL: $API_URL"
echo ""
echo "👉 NEXT STEP: Run './scripts/build-docker.sh' to build and push fresh images."
