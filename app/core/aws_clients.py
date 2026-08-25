import os
import boto3
from app.config import settings

# Determine AWS credentials
aws_access_key_id = getattr(settings, "AWS_ACCESS_KEY_ID", None) or os.getenv("AWS_ACCESS_KEY_ID", "test")
aws_secret_access_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None) or os.getenv("AWS_SECRET_ACCESS_KEY", "test")

# Determine region and endpoint with consistent fallbacks
aws_region = getattr(settings, "AWS_REGION", None) or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
endpoint_url = getattr(settings, "ENDPOINT_URL", None) or os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")

# Unified AWS Clients with explicit LocalStack endpoint fallback
s3_client = boto3.client(
    "s3",
    endpoint_url=endpoint_url,
    region_name=aws_region,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)

sqs_client = boto3.client(
    "sqs",
    endpoint_url=endpoint_url,
    region_name=aws_region,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)

dynamodb_resource = boto3.resource(
    "dynamodb",
    endpoint_url=endpoint_url,
    region_name=aws_region,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)

# Active DynamoDB Table Resource
table = dynamodb_resource.Table(settings.DYNAMODB_TABLE_NAME)