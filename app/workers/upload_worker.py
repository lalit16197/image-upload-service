import json
import os
import time
import boto3
from urllib.parse import unquote_plus
from app.config import settings

aws_region = getattr(settings, "AWS_REGION", None) or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
endpoint_url = getattr(settings, "ENDPOINT_URL", None) or os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")

sqs_client = boto3.client(
    "sqs", endpoint_url=endpoint_url, region_name=aws_region,
    aws_access_key_id="test", aws_secret_access_key="test"
)
dynamodb = boto3.resource(
    "dynamodb", endpoint_url=endpoint_url, region_name=aws_region,
    aws_access_key_id="test", aws_secret_access_key="test"
)
table = dynamodb.Table(getattr(settings, "DYNAMODB_TABLE_NAME", "ImagesMetadata"))


def upload_worker_handler(event, context):
    """Processes S3 ObjectCreated events from SQS and populates DynamoDB."""
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            body = json.loads(record.get("body", "{}"))
            s3_data = json.loads(body["Message"]) if "Message" in body else body

            for s3_record in s3_data.get("Records", []):
                bucket_name = s3_record["s3"]["bucket"]["name"]
                s3_key = unquote_plus(s3_record["s3"]["object"]["key"])
                
                parts = s3_key.split("/")
                if len(parts) >= 3:
                    owner_id = parts[1]
                    image_id = parts[2]
                else:
                    continue

                # Automatically save metadata record to DynamoDB upon successful S3 upload
                table.put_item(
                    Item={
                        "PK": f"OWNER#{owner_id}",
                        "SK": f"IMAGE#{image_id}",
                        "image_id": image_id,
                        "owner_id": owner_id,
                        "s3_key": s3_key,
                        "status": "AVAILABLE",
                    }
                )
                print(f"[Upload Worker] Indexed image {image_id} for owner {owner_id}")

        except Exception as e:
            print(f"[Error] Upload worker failed to process {message_id}: {e}")
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}