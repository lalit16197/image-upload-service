#!/usr/bin/env bash
set -eo pipefail

S3_BUCKET_NAME="instagram-images-bucket"
DYNAMODB_TABLE_NAME="ImagesMetadata"
UPLOAD_QUEUE_NAME="image-upload-queue"
DELETE_QUEUE_NAME="image-delete-queue"

echo "============================================================"
echo "      INITIALIZING LOCALSTACK AWS INFRASTRUCTURE RESOURCE    "
echo "============================================================"

# 1. Check and Create S3 Bucket
echo "[1/3] Checking S3 Bucket: ${S3_BUCKET_NAME}..."
if awslocal s3api head-bucket --bucket "${S3_BUCKET_NAME}" 2>/dev/null; then
    echo "  -> S3 bucket '${S3_BUCKET_NAME}' already exists. Skipping creation."
else
    echo "  -> Provisioning S3 Bucket..."
    until awslocal s3 mb "s3://${S3_BUCKET_NAME}" 2>/dev/null; then
        echo "  -> S3 service not ready yet, retrying in 2 seconds..."
        sleep 2
    done
fi

# Enable/Ensure CORS on S3 Bucket
echo "  -> Applying CORS configuration to S3 Bucket..."
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

# 2. Check and Create SQS Queues
echo "[2/3] Checking SQS Queues..."
for queue in "${UPLOAD_QUEUE_NAME}" "${DELETE_QUEUE_NAME}"; do
    if awslocal sqs get-queue-url --queue-name "${queue}" 2>/dev/null; then
        echo "  -> Queue '${queue}' already exists. Skipping."
    else
        echo "  -> Provisioning Queue '${queue}'..."
        awslocal sqs create-queue --queue-name "${queue}" 2>/dev/null || true
    fi
done

# 3. Configure S3 Event Notification to send 'ObjectCreated' to UPLOAD_QUEUE
echo "  -> Linking S3 Bucket events to SQS Queue (${UPLOAD_QUEUE_NAME})..."
QUEUE_ARN="arn:aws:sqs:us-east-1:000000000000:${UPLOAD_QUEUE_NAME}"

awslocal s3api put-bucket-notification-configuration \
    --bucket "${S3_BUCKET_NAME}" \
    --notification-configuration "{
        \"QueueConfigurations\": [
            {
                \"Id\": \"ImageUploadEvent\",
                \"QueueArn\": \"${QUEUE_ARN}\",
                \"Events\": [\"s3:ObjectCreated:*\"]
            }
        ]
    }" 2>/dev/null || echo "  -> Note: Notification configuration skipped or already set."

# 4. Check and Create DynamoDB Table
echo "[3/3] Checking DynamoDB Table: ${DYNAMODB_TABLE_NAME}..."
if awslocal dynamodb describe-table --table-name "${DYNAMODB_TABLE_NAME}" 2>/dev/null; then
    echo "  -> DynamoDB table '${DYNAMODB_TABLE_NAME}' already exists. Skipping creation."
else
    echo "  -> Provisioning DynamoDB Table..."
    awslocal dynamodb create-table \
        --table-name "${DYNAMODB_TABLE_NAME}" \
        --attribute-definitions \
            AttributeName=PK,AttributeType=S \
            AttributeName=SK,AttributeType=S \
            AttributeName=GSI1PK,AttributeType=S \
            AttributeName=GSI1SK,AttributeType=S \
        --key-schema \
            AttributeName=PK,KeyType=HASH \
            AttributeName=SK,KeyType=RANGE \
        --global-secondary-indexes \
            "[
                {
                    \"IndexName\": \"GSI1Index\",
                    \"KeySchema\": [
                        {\"AttributeName\":\"GSI1PK\",\"KeyType\":\"HASH\"},
                        {\"AttributeName\":\"GSI1SK\",\"KeyType\":\"RANGE\"}
                    ],
                    \"Projection\": {\"ProjectionType\":\"ALL\"}
                }
            ]" \
        --billing-mode PAY_PER_REQUEST 2>/dev/null || true
fi

echo "============================================================"
echo "    LOCALSTACK INFRASTRUCTURE CHECK & PROVISION COMPLETE   "
echo "============================================================"