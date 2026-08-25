import time
import boto3
import requests

from app.config import settings
from app.core.aws_clients import s3_client, table
from app.services.metadata_service import MetadataService
from app.services.storage_service import StorageService

# Configuration
LOCALSTACK_ENDPOINT = settings.ENDPOINT_URL or "http://127.0.0.1:4566"
UPLOAD_QUEUE_URL = settings.UPLOAD_QUEUE_URL
DELETE_QUEUE_URL = settings.DELETE_QUEUE_URL
AWS_REGION = settings.AWS_REGION


def purge_sqs_queues(sqs_client):
    """Purge all stale messages from upload and delete SQS queues before testing."""
    print("[Pre-Test Setup] Purging stale messages from SQS Queues...")
    for queue_url in [UPLOAD_QUEUE_URL, DELETE_QUEUE_URL]:
        try:
            sqs_client.purge_queue(QueueUrl=queue_url)
        except Exception as e:
            print(f"  -> SQS Purge warning for {queue_url}: {str(e)}")
    time.sleep(1.5)
    print("  -> SQS Queues purged successfully.")


def poll_for_hard_deletion(user_id: str, image_id: str, s3_key: str, max_wait_seconds: int = 30, poll_interval: int = 2) -> bool:
    """Poll S3 and DynamoDB until the background worker purges both resources."""
    start_time = time.time()
    pk = f"OWNER#{user_id}"
    sk = f"IMAGE#{image_id}"

    while time.time() - start_time < max_wait_seconds:
        # Check DynamoDB record
        db_res = table.get_item(Key={"PK": pk, "SK": sk})
        item_exists_in_db = "Item" in db_res

        # Check S3 object existence
        try:
            s3_client.head_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
            item_exists_in_s3 = True
        except Exception:
            item_exists_in_s3 = False

        if not item_exists_in_db and not item_exists_in_s3:
            elapsed = round(time.time() - start_time, 2)
            print(f"  -> Background Worker purged S3 & DynamoDB in {elapsed}s")
            return True

        time.sleep(poll_interval)

    return False


def run_e2e_test():
    print("=" * 60)
    print("STARTING INSTAGRAM SERVICE LOCALSTACK END-TO-END TEST")
    print("=" * 60)

    sqs = boto3.client("sqs", endpoint_url=LOCALSTACK_ENDPOINT, region_name=AWS_REGION)

    # 0. Flush queue backlogs before starting test
    purge_sqs_queues(sqs)

    # Payload Parameters
    user_id = "user_mario_42"
    file_name = "vacation_photo.jpg"
    category = "travel"
    tag = "beach"
    sample_image_bytes = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00\x48"

    # -------------------------------------------------------------------------
    # STEP 1: Request Presigned Multipart Upload URLs
    # -------------------------------------------------------------------------
    print("\n[Step 1] Requesting Presigned Upload URLs from StorageService...")
    init_res = StorageService.initiate_multipart_upload(
        user_id=user_id,
        file_name=file_name,
        total_parts=1,
    )

    image_id = init_res["image_id"]
    upload_id = init_res["upload_id"]
    s3_key = init_res["s3_key"]
    upload_url = init_res["part_urls"][0]["upload_url"]

    print(f"  -> Generated Image ID : {image_id}")
    print(f"  -> Target S3 Key      : {s3_key}")
    print(f"  -> Upload ID          : {upload_id}")

    # -------------------------------------------------------------------------
    # STEP 2: Direct Binary Upload to S3 & Complete Multipart Upload
    # -------------------------------------------------------------------------
    print("\n[Step 2] Uploading binary payload to S3 & completing upload...")
    put_response = requests.put(
        upload_url,
        data=sample_image_bytes,
        headers={"Content-Type": "image/jpeg"},
    )
    assert put_response.status_code == 200, f"S3 Upload failed: {put_response.text}"

    etag = put_response.headers.get("ETag", "").replace('"', "")
    StorageService.complete_multipart_upload(
        s3_key=s3_key,
        upload_id=upload_id,
        parts=[{"PartNumber": 1, "ETag": etag}],
    )

    # Persist metadata record
    MetadataService.save_metadata(
        image_id=image_id,
        user_id=user_id,
        category=category,
        tag=tag,
        filename=file_name,
        s3_key=s3_key,
        size_bytes=len(sample_image_bytes),
    )
    print("  -> Upload completed and metadata stored as AVAILABLE.")

    # -------------------------------------------------------------------------
    # STEP 3: Verify Query Capabilities (Active Record)
    # -------------------------------------------------------------------------
    print("\n[Step 3] Querying active items from DynamoDB...")
    owner_matches = MetadataService.list_images_by_owner(user_id=user_id)
    category_matches = MetadataService.list_images_by_category(category=category)

    assert len(owner_matches) > 0, "ERROR: Image not indexed under Owner!"
    assert len(category_matches) > 0, "ERROR: Image not indexed under Category!"
    print(f"  -> Owner Index match found: {owner_matches[0]['image_id']}")
    print(f"  -> Category Index match found: {category_matches[0]['image_id']}")

    # -------------------------------------------------------------------------
    # STEP 4: Soft Delete Execution (Immediate API Response + SQS Enqueue)
    # -------------------------------------------------------------------------
    print("\n[Step 4] Executing MetadataService.soft_delete_and_queue()...")
    is_deleted = MetadataService.soft_delete_and_queue(
        user_id=user_id,
        image_id=image_id,
        s3_key=s3_key,
    )
    assert is_deleted is True, "ERROR: soft_delete_and_queue returned False!"
    print("  -> Soft delete status set to PENDING_DELETE & SQS delete job enqueued.")

    # -------------------------------------------------------------------------
    # STEP 5: Instant Read Filtering Verification
    # -------------------------------------------------------------------------
    print("\n[Step 5] Verifying instant API exclusion via soft-delete filter...")
    active_owner_items = MetadataService.list_images_by_owner(user_id=user_id)
    active_category_items = MetadataService.list_images_by_category(category=category)

    deleted_owner_ids = [item["image_id"] for item in active_owner_items]
    deleted_cat_ids = [item["image_id"] for item in active_category_items]

    assert image_id not in deleted_owner_ids, "ERROR: Soft-deleted item visible in Owner query!"
    assert image_id not in deleted_cat_ids, "ERROR: Soft-deleted item visible in Category query!"
    print("  -> Success: Image is hidden from list queries.")

    # -------------------------------------------------------------------------
    # STEP 6: Poll for Asynchronous Hard Delete (S3 + DynamoDB Purge)
    # -------------------------------------------------------------------------
    print("\n[Step 6] Polling for background SQS Worker hard deletion...")
    hard_delete_done = poll_for_hard_deletion(
        user_id=user_id,
        image_id=image_id,
        s3_key=s3_key,
        max_wait_seconds=30,
    )
    assert hard_delete_done is True, "ERROR: Worker failed to delete S3 object or DynamoDB item within timeout!"

    print("\n" + "=" * 60)
    print("E2E WORKFLOW SUCCESSFUL - COMPLETE LIFECYCLE VERIFIED:")
    print("=" * 60)
    print("  • Multipart Presigned Upload OK")
    print("  • S3 Binary Upload OK")
    print("  • Single-Table DynamoDB GSI Search Queries OK")
    print("  • Synchronous Soft Delete Filtering OK")
    print("  • Asynchronous SQS Lambda Hard Deletion (S3 + DynamoDB) OK")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_e2e_test()