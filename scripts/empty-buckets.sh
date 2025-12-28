#!/bin/bash

# Get Bucket Names (if Terraform state is accessible)
# If Terraform is locked/running, we might need to rely on the known naming convention or user to provide them.
# Or, simpler: List all buckets matching the project pattern.

PROJECT_NAME="podcast-transcription" 
# Note: Account ID is needed if we strictly follow the naming convention in main.tf: 
# "${var.project_name}-raw-${data.aws_caller_identity.current.account_id}"

echo "🧹 Finding project buckets..."
BUCKETS=$(aws s3 ls | grep "$PROJECT_NAME" | awk '{print $3}')

if [ -z "$BUCKETS" ]; then
    echo "No buckets found matching '$PROJECT_NAME'."
    exit 0
fi

echo "Found buckets:"
echo "$BUCKETS"
echo ""

read -p "⚠️  Are you sure you want to EMPTY and DELETE contents of these buckets? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborting."
    exit 1
fi

for bucket in $BUCKETS; do
    echo "🗑️  Emptying bucket: $bucket"
    aws s3 rm "s3://$bucket" --recursive
done

echo "✅ Buckets emptied."
