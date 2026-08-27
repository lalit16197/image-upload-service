import pytest
from boto3.dynamodb.conditions import Key


def test_initiate_multipart_upload_success(mock_aws_setup):
    """Verify presigned upload initialization generates correct metadata and structural keys."""
    from app.services.storage_service import StorageService

    result = StorageService.initiate_multipart_upload(
        user_id="user_mario_42",
        file_name="vacation.jpg",
        category="travel",
        tag="beach",
        total_parts=2,
    )

    assert "upload_id" in result
    assert "image_id" in result
    assert len(result["part_urls"]) == 2
    assert result["s3_key"].startswith("uploads/user_mario_42/")


def test_save_and_list_images_by_owner(mock_aws_setup):
    """Verify metadata persistence and owner retrieval capabilities."""
    from app.services.storage_service import StorageService

    StorageService.save_metadata(
        image_id="img_001",
        user_id="user_mario_42",
        category="travel",
        tag="beach",
        filename="vacation.jpg",
        s3_key="uploads/user_mario_42/img_001/vacation.jpg",
        size_bytes=4096,
    )

    items = StorageService.list_images(owner_id="user_mario_42")
    assert len(items) == 1
    assert items[0]["image_id"] == "img_001"
    assert items[0]["status"] == "AVAILABLE"


def test_list_images_by_gsi_filters(mock_aws_setup):
    """Verify category and tag searches use their respective indexes."""
    from app.services.storage_service import StorageService

    StorageService.save_metadata("img_01", "u1", "travel", "beach", "f1.jpg", "k1", 100)
    StorageService.save_metadata("img_02", "u2", "sports", "soccer", "f2.jpg", "k2", 200)

    category_results = StorageService.list_images(category="travel")
    tag_results = StorageService.list_images(tag="soccer")

    assert len(category_results) == 1
    assert category_results[0]["image_id"] == "img_01"

    assert len(tag_results) == 1
    assert tag_results[0]["image_id"] == "img_02"


def test_save_metadata_creates_gsi3_records_per_tag(mock_aws_setup):
    from app.services.storage_service import StorageService

    StorageService.save_metadata(
        image_id="img_gsi3",
        owner_id="u1",
        category="travel",
        tags=["beach", "summer"],
        filename="goa.jpg",
        s3_key="goa",
        size_bytes=100,
    )

    beach_items = mock_aws_setup["table"].query(
        IndexName="GSI3Index",
        KeyConditionExpression=Key(
            "GSI3PK"
        ).eq("CATEGORY#travel#TAG#beach"),
    )["Items"]
    summer_items = mock_aws_setup["table"].query(
        IndexName="GSI3Index",
        KeyConditionExpression=Key(
            "GSI3PK"
        ).eq("CATEGORY#travel#TAG#summer"),
    )["Items"]

    assert [item["image_id"] for item in beach_items] == ["img_gsi3"]
    assert [item["image_id"] for item in summer_items] == ["img_gsi3"]


def test_list_images_by_multiple_tags(mock_aws_setup):
    from app.services.storage_service import StorageService

    StorageService.save_metadata(
        image_id="img_multi",
        owner_id="u1",
        category="travel",
        tags=["beach", "summer"],
        filename="f.jpg",
        s3_key="k",
        size_bytes=100,
    )
    StorageService.save_metadata(
        image_id="img_single",
        owner_id="u1",
        category="travel",
        tags=["beach"],
        filename="g.jpg",
        s3_key="g",
        size_bytes=100,
    )

    results = StorageService.list_images(tags="beach,summer")

    assert [item["image_id"] for item in results] == ["img_multi"]


def test_list_images_by_category_and_multiple_tags_uses_gsi3(mock_aws_setup):
    from app.services.storage_service import StorageService

    StorageService.save_metadata(
        image_id="img_travel",
        owner_id="u1",
        category="travel",
        tags=["beach", "summer"],
        filename="travel.jpg",
        s3_key="travel",
        size_bytes=100,
    )
    StorageService.save_metadata(
        image_id="img_sports",
        owner_id="u1",
        category="sports",
        tags=["beach", "summer"],
        filename="sports.jpg",
        s3_key="sports",
        size_bytes=100,
    )

    results = StorageService.list_images(
        category="travel",
        tags="beach,summer",
    )

    assert [item["image_id"] for item in results] == ["img_travel"]


def test_delete_image_async_soft_delete(mock_aws_setup):
    """Verify soft-delete updates record status and immediately hides items from queries."""
    from app.services.storage_service import StorageService

    # 1. Store Record
    StorageService.save_metadata("img_99", "u1", "art", "sketch", "art.jpg", "key99", 500)

    # 2. Perform Async Soft Delete
    is_deleted = StorageService.delete_image_async(user_id="u1", image_id="img_99")
    assert is_deleted is True

    # 3. Assert Immediate Filtering Excludes Soft-Deleted Record
    active_items = StorageService.list_images(owner_id="u1")
    assert len(active_items) == 0