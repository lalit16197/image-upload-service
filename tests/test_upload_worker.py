import json


def _event(key):
    return {
        "Records": [{
            "messageId": "upload-message",
            "body": json.dumps({
                "Records": [{
                    "s3": {
                        "bucket": {"name": "test-instagram-quarantine"},
                        "object": {"key": key},
                    }
                }]
            }),
        }]
    }


def test_upload_worker_promotes_valid_image_and_indexes_metadata(mock_aws_setup):
    from app.workers.upload_worker import upload_worker_handler

    key = "uploads/user-1/image-1/photo.jpg"
    mock_aws_setup["s3"].put_object(
        Bucket="test-instagram-quarantine",
        Key=key,
        Body=b"\xff\xd8\xffvalid-image",
        ContentType="image/jpeg",
        Metadata={"category": "travel", "tag": "beach", "filename": "photo.jpg"},
    )

    result = upload_worker_handler(_event(key), None)

    assert result == {"batchItemFailures": []}
    assert mock_aws_setup["s3"].head_object(
        Bucket="test-instagram-bucket", Key=key
    )["ContentLength"] > 0
    item = mock_aws_setup["table"].get_item(
        Key={"PK": "OWNER#user-1", "SK": "IMAGE#image-1"}
    )["Item"]
    assert item["status"] == "AVAILABLE"
    assert item["tag"] == "beach"


def test_upload_worker_rejects_invalid_image(mock_aws_setup):
    from app.workers.upload_worker import upload_worker_handler

    key = "uploads/user-1/image-2/photo.jpg"
    mock_aws_setup["s3"].put_object(
        Bucket="test-instagram-quarantine",
        Key=key,
        Body=b"not-an-image",
        ContentType="image/jpeg",
    )

    result = upload_worker_handler(_event(key), None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "upload-message"}]}
    assert "Contents" not in mock_aws_setup["s3"].list_objects_v2(
        Bucket="test-instagram-quarantine", Prefix=key
    )
