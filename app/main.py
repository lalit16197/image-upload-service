from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel
from typing import Optional, List
from app.services.storage_service import StorageService
from app.services.metadata_service import MetadataService

app = FastAPI(
    title="Instagram Image Storage & Processing Service",
    description="Scalable cloud image storage system with presigned URLs and async soft/hard deletion.",
    version="1.0.0"
)

# --- Schemas ---
class InitiateUploadRequest(BaseModel):
    owner_id: str
    file_name: str
    content_type: str = "image/jpeg"
    category: str = "general"
    caption: Optional[str] = ""

class ImageItemResponse(BaseModel):
    image_id: str
    owner_id: str
    category: str
    status: str
    s3_key: str
    created_at: str
    caption: Optional[str] = None


# --- 1. Upload Image (Initiate Multipart Upload & Presigned URL) ---
@app.post("/api/v1/images/upload-url", status_code=status.HTTP_201_CREATED)
def initiate_image_upload(payload: InitiateUploadRequest):
    """
    Task 1.1: Generates presigned S3 upload configuration and initializes 
    the metadata lifecycle in DynamoDB.
    """
    upload_data = StorageService.initiate_multipart_upload(
        owner_id=payload.owner_id,
        file_name=payload.file_name,
        content_type=payload.content_type
    )
    
    MetadataService.save_metadata(
        image_id=upload_data["image_id"],
        owner_id=payload.owner_id,
        category=payload.category,
        s3_key=upload_data["s3_key"],
        caption=payload.caption
    )
    
    return upload_data


# --- 2. List Images (Filter by Owner ID or Category) ---
@app.get("/api/v1/images", response_model=List[ImageItemResponse])
def list_images(
    owner_id: Optional[str] = Query(None, description="Filter images by Owner ID (uses GSI1)"),
    category: Optional[str] = Query(None, description="Filter images by Category (uses GSI2)")
):
    """
    Task 1.2: Lists active images. Supports filtering by Owner ID or Category.
    Automatically excludes items marked as PENDING_DELETE.
    """
    if owner_id:
        items = MetadataService.query_by_owner(owner_id)
    elif category:
        items = MetadataService.query_by_category(category)
    else:
        raise HTTPException(
            status_code=400, 
            detail="At least one filter parameter ('owner_id' or 'category') must be provided."
        )
    return items


# --- 3. View / Download Image (Get Presigned Read URL) ---
@app.get("/api/v1/images/{owner_id}/{image_id}/download")
def get_image_download_url(owner_id: str, image_id: str):
    """
    Task 1.3: Generates a temporary GET presigned URL for secure image viewing/downloading.
    """
    metadata = MetadataService.get_image(owner_id=owner_id, image_id=image_id)
    if not metadata or metadata.get("status") == "PENDING_DELETE":
        raise HTTPException(status_code=404, detail="Image not found or has been deleted.")

    presigned_url = StorageService.generate_download_url(s3_key=metadata["s3_key"])
    return {"image_id": image_id, "download_url": presigned_url}


# --- 4. Delete Image (Soft Delete + Async SQS Purge) ---
@app.delete("/api/v1/images/{owner_id}/{image_id}", status_code=status.HTTP_202_ACCEPTED)
def delete_image(owner_id: str, image_id: str):
    """
    Task 1.4: Marks the image status as PENDING_DELETE in DynamoDB (soft delete)
    and dispatches a message to SQS for background S3/DynamoDB hard deletion.
    """
    metadata = MetadataService.get_image(owner_id=owner_id, image_id=image_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Image not found.")
    
    MetadataService.soft_delete_and_queue(
        owner_id=owner_id,
        image_id=image_id,
        s3_key=metadata["s3_key"]
    )
    return {"message": "Image deletion initiated.", "image_id": image_id}