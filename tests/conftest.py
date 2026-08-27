import os
import boto3
import pytest
from moto import mock_aws

# Force mock environment variables before any module import
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["S3_BUCKET_NAME"] = "test-instagram-bucket"
os.environ["QUARANTINE_BUCKET_NAME"] = "test-instagram-quarantine"
os.environ["DYNAMODB_TABLE_NAME"] = "TestImagesMetadata"

# Wipe LocalStack endpoint variables to ensure Moto operates entirely in memory
os.environ.pop("AWS_ENDPOINT_URL", None)
os.environ.pop("LOCALSTACK_HOSTNAME", None)


@pytest.fixture(scope="function")
def aws_credentials():
    """Ensure AWS environment variables remain locked during test execution."""
    return True


@pytest.fixture(scope="function")
def mock_aws_setup(aws_credentials):
    """Initializes in-memory S3, Single-Table DynamoDB, and SQS resources."""
    with mock_aws():
        region = "us-east-1"
        bucket_name = "test-instagram-bucket"
        table_name = "TestImagesMetadata"

        # 1. Setup S3
        s3_client = boto3.client("s3", region_name=region)
        s3_client.create_bucket(Bucket=bucket_name)
        s3_client.create_bucket(Bucket="test-instagram-quarantine")

        # 2. Setup Single-Table DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name=region)
        table = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
                {"AttributeName": "GSI3PK", "AttributeType": "S"},
                {"AttributeName": "GSI3SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1Index",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2Index",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI3Index",
                    "KeySchema": [
                        {"AttributeName": "GSI3PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI3SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # 3. Setup SQS Delete Queue
        sqs_client = boto3.client("sqs", region_name=region)
        sqs_queue = sqs_client.create_queue(QueueName="image-delete-queue")
        upload_queue = sqs_client.create_queue(QueueName="image-upload-queue")

        from app.config import settings
        from app.core import aws_clients
        from app.services import metadata_service, storage_service
        from app.workers import upload_worker
        settings.S3_BUCKET_NAME = bucket_name
        settings.QUARANTINE_BUCKET_NAME = "test-instagram-quarantine"
        settings.DYNAMODB_TABLE_NAME = table_name
        settings.DELETE_QUEUE_URL = sqs_queue["QueueUrl"]
        settings.UPLOAD_QUEUE_URL = upload_queue["QueueUrl"]
        aws_clients.s3_client = s3_client
        aws_clients.presign_s3_client = s3_client
        aws_clients.table = table
        aws_clients.sqs_client = sqs_client
        metadata_service.table = table
        metadata_service.sqs_client = sqs_client
        storage_service.s3_client = s3_client
        storage_service.presign_s3_client = s3_client
        upload_worker.s3_client = s3_client

        yield {
            "s3": s3_client,
            "dynamodb": dynamodb,
            "table": table,
            "sqs": sqs_client,
            "queue_url": sqs_queue["QueueUrl"],
        }