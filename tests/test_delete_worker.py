import json
import pytest


def test_delete_worker_handler_success(mock_aws_setup):
    """Verify worker permanently deletes both S3 file binary and DynamoDB item."""
    from app.services.storage_service import delete_worker_handler

    s3_client = mock_aws_setup["s3"]
    table = mock_aws_setup["table"]
    bucket_name = "test-instagram-bucket"

    # Setup Pre-existing resources
    user_id = "user_test_99"
    image_id = "img_abc123"
    pk = f"OWNER#{user_id}"
    sk = f"IMAGE#{image_id}"
    s3_key = f"uploads/{user_id}/{image_id}/sample.jpg"

    s3_client.put_object(Bucket=bucket_name, Key=s3_key, Body=b"binary_data")
    table.put_item(
        Item={
            "PK": pk,
            "SK": sk,
            "image_id": image_id,
            "s3_key": s3_key,
            "status": "PENDING_DELETE",
        }
    )

    # Mock SQS Event Payload
    event = {
        "Records": [
            {
                "messageId": "msg-111",
                "body": json.dumps({"pk": pk, "sk": sk, "s3_key": s3_key, "image_id": image_id}),
            }
        ]
    }

    response = delete_worker_handler(event, context=None)

    # Assertions
    assert response == {"batchItemFailures": []}

    # Verify S3 Purge
    s3_objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=s3_key)
    assert s3_objects.get("KeyCount", 0) == 0

    # Verify DynamoDB Hard Delete
    db_res = table.get_item(Key={"PK": pk, "SK": sk})
    assert "Item" not in db_res


def test_delete_worker_handler_batch_failure_handling(mock_aws_setup):
    """Verify SQS batchItemFailures returns malformed message identifiers for standard retries."""
    from app.services.storage_service import delete_worker_handler

    bad_event = {
        "Records": [
            {
                "messageId": "corrupted-msg-id-001",
                "body": "MALFORMED_NON_JSON_PAYLOAD",
            }
        ]
    }

    response = delete_worker_handler(bad_event, context=None)
    assert response == {"batchItemFailures": [{"itemIdentifier": "corrupted-msg-id-001"}]}