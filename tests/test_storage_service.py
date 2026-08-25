import pytest


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
    """Verify Global Secondary Index (GSI1) filtering by category and tag."""
    from app.services.storage_service import StorageService

    StorageService.save_metadata("img_01", "u1", "travel", "beach", "f1.jpg", "k1", 100)
    StorageService.save_metadata("img_02", "u2", "sports", "soccer", "f2.jpg", "k2", 200)

    category_results = StorageService.list_images(category="travel")
    tag_results = StorageService.list_images(tag="soccer")

    assert len(category_results) == 1
    assert category_results[0]["image_id"] == "img_01"

    assert len(tag_results) == 1
    assert tag_results[0]["image_id"] == "img_02"


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