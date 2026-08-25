#!/usr/bin/env bash
set -eo pipefail

MARKER_FILE="/var/lib/localstack/initialized"

# Check if initial setup was already completed
if [ -f "$MARKER_FILE" ]; then
    echo "--- Resources already exist from persisted volume. Skipping initialization. ---"
    exit 0
fi

echo "============================================================"
echo "      INITIALIZING LOCALSTACK AWS INFRASTRUCTURE RESOURCE    "
echo "============================================================"

# Define resource configuration names matching docker-compose.yml
S3_BUCKET_NAME="instagram-images-bucket"
DYNAMODB_TABLE_NAME="ImagesMetadata"
UPLOAD_QUEUE_NAME="image-upload-queue"
DELETE_QUEUE_NAME="image-delete-queue"

# 1. Create S3 Bucket
echo "[1/3] Provisioning S3 Bucket: ${S3_BUCKET_NAME}..."
awslocal s3 mb "s3://${S3_BUCKET_NAME}" 2>/dev/null || echo "  -> S3 bucket '${S3_BUCKET_NAME}' already exists."

# Enable CORS on S3 Bucket for Presigned Uploads
awslocal s3api put-bucket-cors --bucket "${S3_BUCKET_NAME}" --cors-configuration '{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
      "AllowedOrigins": ["*"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}' 2>/dev/null || true

# 2. Create SQS Queues
echo "[2/3] Provisioning SQS Queues..."
awslocal sqs create-queue --queue-name "${UPLOAD_QUEUE_NAME}" 2>/dev/null || echo "  -> Queue '${UPLOAD_QUEUE_NAME}' already exists."
awslocal sqs create-queue --queue-name "${DELETE_QUEUE_NAME}" 2>/dev/null || echo "  -> Queue '${DELETE_QUEUE_NAME}' already exists."

# 3. Create DynamoDB Single-Table Design with GSIs
echo "[3/3] Provisioning DynamoDB Table: ${DYNAMODB_TABLE_NAME}..."
awslocal dynamodb create-table \
    --table-name "${DYNAMODB_TABLE_NAME}" \
    --attribute-definitions \
        AttributeName=PK,AttributeType=S \
        AttributeName=SK,AttributeType=S \
        AttributeName=GSI1PK,AttributeType=S \
        AttributeName=GSI1SK,AttributeType=S \
        AttributeName=GSI2PK,AttributeType=S \
        AttributeName=GSI2SK,AttributeType=S \
    --key-schema \
        AttributeName=PK,KeyType=HASH \
        AttributeName=SK,KeyType=RANGE \
    --global-secondary-indexes \
        "[
            {
                \"IndexName\": \"GSI1\",
                \"KeySchema\": [
                    {\"AttributeName\":\"GSI1PK\",\"KeyType\":\"HASH\"},
                    {\"AttributeName\":\"GSI1SK\",\"KeyType\":\"RANGE\"}
                ],
                \"Projection\": {\"ProjectionType\":\"ALL\"}
            },
            {
                \"IndexName\": \"GSI2\",
                \"KeySchema\": [
                    {\"AttributeName\":\"GSI2PK\",\"KeyType\":\"HASH\"},
                    {\"AttributeName\":\"GSI2SK\",\"KeyType\":\"RANGE\"}
                ],
                \"Projection\": {\"ProjectionType\":\"ALL\"}
            }
        ]" \
    --billing-mode PAY_PER_REQUEST 2>/dev/null || echo "  -> DynamoDB table '${DYNAMODB_TABLE_NAME}' already exists."

# Create marker file to signal initialization completion
mkdir -p /var/lib/localstack
touch "$MARKER_FILE"

echo "============================================================"
echo "    LOCALSTACK INFRASTRUCTURE PROVISIONING COMPLETE        "
echo "============================================================"