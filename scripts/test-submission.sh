#!/bin/bash

# Get API URL from Terraform if not provided
API_URL=$1
if [ -z "$API_URL" ]; then
    echo "🔍 Getting API URL from Terraform..."
    cd ../terraform
    API_URL=$(terraform output -raw api_gateway_url)
    cd ../scripts
fi

if [ -z "$API_URL" ]; then
    echo "❌ Could not get API URL. Please provide it as the first argument."
    echo "Usage: ./test-submission.sh <API_URL> [YOUTUBE_URL]"
    exit 1
fi

# YouTube URL to test (default: specific video)
VIDEO_URL=${2:-"https://peertube.tv/w/eVYnv2DSiNZjehs1tm39xH"} # Reliable test URL (no bot detection)
echo "🚀 Submitting Job to: $API_URL/jobs"
echo "📺 Video URL: $VIDEO_URL"

RESPONSE=$(curl -s -X POST "$API_URL/jobs" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"$VIDEO_URL\"}")

echo "📄 Response: $RESPONSE"

JOB_ID=$(echo $RESPONSE | grep -o '"jobId": "[^"]*' | cut -d'"' -f4)

if [ -n "$JOB_ID" ]; then
    echo "✅ Job submitted successfully! Job ID: $JOB_ID"
    echo ""
    echo "To check status:"
    echo "  ./check-status.sh $API_URL $JOB_ID"
else
    echo "❌ Failed to get Job ID from response."
fi
