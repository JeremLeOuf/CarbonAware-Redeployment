#!/bin/bash
# scripts/setup-terraform-backend.sh

BUCKET_NAME="carbon-aware-terraform-state-${RANDOM}"
TABLE_NAME="terraform-state-lock"
REGION="us-east-1"

# Create S3 bucket for state
aws s3api create-bucket \
    --bucket $BUCKET_NAME \
    --region $REGION

# Enable versioning
aws s3api put-bucket-versioning \
    --bucket $BUCKET_NAME \
    --versioning-configuration Status=Enabled

# Create DynamoDB table for locking
aws dynamodb create-table \
    --table-name $TABLE_NAME \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region $REGION

echo "✅ Backend created. Update backend.tf with bucket: $BUCKET_NAME"