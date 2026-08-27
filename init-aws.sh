#!/usr/bin/env bash
set -eo pipefail

S3_BUCKET_NAME="instagram-images-bucket"
QUARANTINE_BUCKET_NAME="instagram-images-quarantine"
DYNAMODB_TABLE_NAME="ImagesMetadata"
UPLOAD_QUEUE_NAME="image-upload-queue"
DELETE_QUEUE_NAME="image-delete-queue"
UPLOAD_DLQ_NAME="image-upload-dlq"

echo "============================================================"
echo "      INITIALIZING LOCALSTACK AWS INFRASTRUCTURE RESOURCE    "
echo "============================================================"

# 1. Check and Create S3 Bucket
echo "[1/3] Checking production and quarantine S3 buckets..."
for bucket in "${S3_BUCKET_NAME}" "${QUARANTINE_BUCKET_NAME}"; do
  if ! awslocal s3api head-bucket --bucket "${bucket}" 2>/dev/null; then
    until awslocal s3 mb "s3://${bucket}" 2>/dev/null; do
      echo "  -> S3 service not ready yet, retrying in 2 seconds..."
      sleep 2
    done
  fi
done

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
awslocal s3api put-bucket-cors --bucket "${QUARANTINE_BUCKET_NAME}" --cors-configuration '{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
      "AllowedOrigins": ["*"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}' 2>/dev/null || true
awslocal s3api put-bucket-lifecycle-configuration --bucket "${QUARANTINE_BUCKET_NAME}" \
  --lifecycle-configuration '{"Rules":[{"ID":"AbortIncompleteMultipartUploads","Status":"Enabled","Filter":{"Prefix":""},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}' 2>/dev/null || true

# 2. Check and Create SQS Queues
echo "[2/3] Checking SQS Queues..."
for queue in "${UPLOAD_QUEUE_NAME}" "${DELETE_QUEUE_NAME}" "${UPLOAD_DLQ_NAME}"; do
    if awslocal sqs get-queue-url --queue-name "${queue}" 2>/dev/null; then
        echo "  -> Queue '${queue}' already exists. Skipping."
    else
        echo "  -> Provisioning Queue '${queue}'..."
        if [ "${queue}" = "${UPLOAD_QUEUE_NAME}" ]; then
          awslocal sqs create-queue --queue-name "${queue}" \
            --attributes VisibilityTimeout=180 2>/dev/null || true
        else
          awslocal sqs create-queue --queue-name "${queue}" 2>/dev/null || true
        fi
    fi
done
DLQ_URL=$(awslocal sqs get-queue-url --queue-name "${UPLOAD_DLQ_NAME}" --query QueueUrl --output text)
DLQ_ARN="arn:aws:sqs:us-east-1:000000000000:${UPLOAD_DLQ_NAME}"
awslocal sqs set-queue-attributes --queue-url "$(awslocal sqs get-queue-url --queue-name "${UPLOAD_QUEUE_NAME}" --query QueueUrl --output text)" \
  --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"${DLQ_ARN}\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}" 2>/dev/null || true

# 3. Configure quarantine S3 ObjectCreated events to send to UPLOAD_QUEUE
echo "  -> Linking S3 Bucket events to SQS Queue (${UPLOAD_QUEUE_NAME})..."
QUEUE_ARN="arn:aws:sqs:us-east-1:000000000000:${UPLOAD_QUEUE_NAME}"

awslocal s3api put-bucket-notification-configuration \
    --bucket "${QUARANTINE_BUCKET_NAME}" \
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
            AttributeName=GSI2PK,AttributeType=S \
            AttributeName=GSI2SK,AttributeType=S \
            AttributeName=GSI3PK,AttributeType=S \
            AttributeName=GSI3SK,AttributeType=S \
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
                },
                {
                    \"IndexName\": \"GSI2Index\",
                    \"KeySchema\": [
                        {\"AttributeName\":\"GSI2PK\",\"KeyType\":\"HASH\"},
                        {\"AttributeName\":\"GSI2SK\",\"KeyType\":\"RANGE\"}
                    ],
                    \"Projection\": {\"ProjectionType\":\"ALL\"}
                },
                {
                    \"IndexName\": \"GSI3Index\",
                    \"KeySchema\": [
                        {\"AttributeName\":\"GSI3PK\",\"KeyType\":\"HASH\"},
                        {\"AttributeName\":\"GSI3SK\",\"KeyType\":\"RANGE\"}
                    ],
                    \"Projection\": {\"ProjectionType\":\"ALL\"}
                }
            ]" \
        --billing-mode PAY_PER_REQUEST 2>/dev/null || true
fi

# Add GSI3 to an existing table created by an older version of this script.
if ! awslocal dynamodb describe-table --table-name "${DYNAMODB_TABLE_NAME}" \
    --query "Table.GlobalSecondaryIndexes[?IndexName=='GSI3Index'].IndexName" \
    --output text 2>/dev/null | grep -q "GSI3Index"; then
  echo "  -> Adding missing GSI3Index to existing DynamoDB table..."
  awslocal dynamodb update-table \
    --table-name "${DYNAMODB_TABLE_NAME}" \
    --attribute-definitions \
      AttributeName=GSI3PK,AttributeType=S \
      AttributeName=GSI3SK,AttributeType=S \
    --global-secondary-index-updates \
      '[{"Create":{"IndexName":"GSI3Index","KeySchema":[{"AttributeName":"GSI3PK","KeyType":"HASH"},{"AttributeName":"GSI3SK","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}}}]' \
    2>/dev/null || true
fi

until [ "$(awslocal dynamodb describe-table --table-name "${DYNAMODB_TABLE_NAME}" \
  --query "Table.TableStatus" --output text 2>/dev/null)" = "ACTIVE" ]; do
  echo "  -> Waiting for DynamoDB table to become ACTIVE..."
  sleep 2
done

echo "============================================================"
echo "    LOCALSTACK INFRASTRUCTURE CHECK & PROVISION COMPLETE   "
echo "============================================================"