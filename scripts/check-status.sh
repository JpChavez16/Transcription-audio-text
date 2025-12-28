#!/bin/bash

API_URL=$1
JOB_ID=$2

if [ -z "$API_URL" ] || [ -z "$JOB_ID" ]; then
    echo "Usage: ./check-status.sh <API_URL> <JOB_ID>"
    exit 1
fi

echo "🔍 Checking status for Job: $JOB_ID"

curl -s -X GET "$API_URL/jobs/$JOB_ID" | python3 -m json.tool
