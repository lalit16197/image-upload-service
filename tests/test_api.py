import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.storage_service import StorageService

client = TestClient(app)

def test_initiate_upload_success(mock_aws_setup):
    payload = {
        "owner_id": "user_test_1",
        "file_name": "test_photo.jpg",
        "content_type": "image/jpeg",
        "category": "nature",
        "tags": ["outdoors", "forest"],
    }
    response = client.post("/api/v1/images/upload-url", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "image_id" in data
    assert "upload_id" in data
    assert "s3_key" in data

def test_list_images_without_filters_fails(mock_aws_setup):
    response = client.get("/api/v1/images")
    assert response.status_code == 400

def test_list_images_by_owner_filter(mock_aws_setup):
    response = client.get("/api/v1/images?owner_id=user_test_1")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_images_by_category_and_tags_filter(mock_aws_setup):
    StorageService.save_metadata(
        image_id="img_api_search",
        owner_id="user_test_1",
        category="nature",
        tags=["outdoors", "forest"],
        filename="forest.jpg",
        s3_key="forest.jpg",
        size_bytes=100,
    )

    response = client.get(
        "/api/v1/images?category=nature&tags=outdoors,forest"
    )

    assert response.status_code == 200
    assert [item["image_id"] for item in response.json()] == ["img_api_search"]


def test_delete_nonexistent_image(mock_aws_setup):
    response = client.delete("/api/v1/images/non_existent_owner/invalid_id")
    assert response.status_code == 404