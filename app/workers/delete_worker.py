import json
from app.services.storage_service import StorageService
from app.services.metadata_service import MetadataService


def delete_worker_handler(event, context):
    """Processes background image purge messages from SQS delete queue."""
    batch_failures = []

    for record in event.get("Records", []):
        msg_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            pk = body["pk"]
            sk = body["sk"]
            s3_key = body["s3_key"]

            # 1. Permanently delete binary asset from S3
            StorageService.delete_s3_object(s3_key)

            # 2. Permanently delete metadata entry from DynamoDB
            MetadataService.hard_delete_metadata(pk, sk)

            print(f"Hard deletion completed for PK={pk}, SK={sk}, S3_KEY={s3_key}")

        except Exception as err:
            print(f"Failed to process deletion record {msg_id}: {err}")
            batch_failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": batch_failures}