import json
import os
import boto3
from urllib.parse import unquote_plus
from app.config import settings
from app.services.metadata_service import MetadataService

aws_region = getattr(settings, "AWS_REGION", None) or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
endpoint_url = getattr(settings, "ENDPOINT_URL", None) or os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")

s3_client = boto3.client(
    "s3", endpoint_url=endpoint_url, region_name=aws_region,
    aws_access_key_id="test", aws_secret_access_key="test"
)

IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}


def _valid_image_header(content_type, header):
    if content_type == "image/webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    return any(header.startswith(signature) for signature in IMAGE_SIGNATURES.get(content_type, ()))


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

                object_info = s3_client.head_object(Bucket=bucket_name, Key=s3_key)
                content_type = object_info.get("ContentType", "")
                if content_type not in IMAGE_SIGNATURES and content_type != "image/webp":
                    raise ValueError("Unsupported image content type")
                header = s3_client.get_object(
                    Bucket=bucket_name, Key=s3_key, Range="bytes=0-15"
                )["Body"].read()
                if not _valid_image_header(content_type, header):
                    s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
                    raise ValueError("Image magic bytes do not match content type")

                s3_client.copy_object(
                    CopySource={"Bucket": bucket_name, "Key": s3_key},
                    Bucket=settings.S3_BUCKET_NAME,
                    Key=s3_key,
                    MetadataDirective="COPY",
                )
                metadata = object_info.get("Metadata", {})
                tags = [
                    tag.strip()
                    for tag in metadata.get("tags", "").split(",")
                    if tag.strip()
                ]
                if not tags and metadata.get("tag"):
                    tags = [metadata["tag"]]
                MetadataService.save_metadata(
                    image_id=image_id,
                    owner_id=metadata.get("owner_id", owner_id),
                    category=metadata.get("category", "general"),
                    tags=tags,
                    caption=metadata.get("caption"),
                    filename=metadata.get("filename", parts[-1]),
                    size_bytes=object_info.get("ContentLength", 0),
                    s3_key=s3_key,
                )
                s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
                print(f"[Upload Worker] Indexed image {image_id} for owner {owner_id}")

        except Exception as e:
            print(f"[Error] Upload worker failed to process {message_id}: {e}")
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}