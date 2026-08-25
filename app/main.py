from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
from typing import Optional, List
import logging

from app.services.storage_service import StorageService
from app.services.metadata_service import MetadataService

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_main")

# --- OpenAPI Tag Definitions ---
tags_metadata = [
    {
        "name": "Image Management",
        "description": "Core operations for presigned upload generation, GSI-filtered querying, viewing, and async soft/hard deletion.",
    },
]

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Instagram Scalable Image Upload & Metadata Service",
    description="""
## Cloud-Native Media Pipeline API

This service supports direct-to-S3 presigned multipart uploads, single-table DynamoDB index lookups, 
and non-blocking asynchronous hard purging using AWS SQS.

### Usage Quickstart:
1. Call **`POST /api/v1/images/upload-url`** to get an S3 presigned upload link and register metadata.
2. Upload binary payload directly to S3 using the generated URL.
3. Query active media assets using **`GET /api/v1/images`** (filters by `owner_id` or `category`).
4. Retrieve secure GET download links using **`GET /api/v1/images/{owner_id}/{image_id}/download`**.
5. Delete media assets asynchronously using **`DELETE /api/v1/images/{owner_id}/{image_id}`**.
    """,
    version="1.0.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# --- Pydantic Request & Response Schemas ---
class InitiateUploadRequest(BaseModel):
    owner_id: str = Field(..., example="user_mario_42", description="Unique identifier of the image owner")
    file_name: str = Field(..., example="vacation.jpg", description="Original filename of the asset")
    content_type: str = Field("image/jpeg", example="image/jpeg", description="MIME content type")
    category: str = Field("general", example="travel", description="Category tag used for GSI indexing")
    caption: Optional[str] = Field(None, example="Summer in Rome", description="Optional text description")

class UploadResponse(BaseModel):
    image_id: str = Field(..., example="2cd6bd3d-700b-4c0f-b216-ae396d07f500")
    s3_key: str = Field(..., example="uploads/user_mario_42/2cd6bd3d-700b-4c0f-b216-ae396d07f500/vacation.jpg")
    upload_id: str = Field(..., example="kQM4siMOcMAwZmCY2mdM...")
    upload_url: str = Field(..., example="http://localhost:4566/instagram-images-bucket/...")

class ImageItemResponse(BaseModel):
    image_id: str
    owner_id: str
    category: str
    status: str
    s3_key: str
    created_at: str
    caption: Optional[str] = None

class DownloadResponse(BaseModel):
    image_id: str
    download_url: str

class MessageResponse(BaseModel):
    message: str
    image_id: str


# --- REST API Endpoints ---

# Task 1.1: Upload Image (Presigned Multipart Upload & Metadata Setup)
@app.post(
    "/api/v1/images/upload-url",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Image Management"],
    summary="Task 1.1: Initiate S3 Presigned Upload",
    response_description="Returns S3 upload configuration and saves initial metadata to DynamoDB."
)
def initiate_image_upload(payload: InitiateUploadRequest):
    """
    Generates a presigned S3 upload configuration and initializes 
    the metadata lifecycle in DynamoDB with AVAILABLE status.
    """
    try:
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
    except Exception as e:
        logger.error(f"Error initiating upload: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to initialize image upload session.")


# Task 1.2: List Images (GSI Filters by Owner or Category)
@app.get(
    "/api/v1/images",
    response_model=List[ImageItemResponse],
    status_code=status.HTTP_200_OK,
    tags=["Image Management"],
    summary="Task 1.2: List active images with search filters",
    response_description="Returns list of active images matching search parameters."
)
def list_images(
    owner_id: Optional[str] = Query(None, description="Filter images by Owner ID (uses GSI1)"),
    category: Optional[str] = Query(None, description="Filter images by Category (uses GSI2)")
):
    """
    Lists active images from DynamoDB. 
    Requires at least one filter parameter (`owner_id` or `category`).
    Automatically excludes items marked as `PENDING_DELETE`.
    """
    if not owner_id and not category:
        raise HTTPException(
            status_code=400, 
            detail="At least one search filter parameter ('owner_id' or 'category') must be specified."
        )

    try:
        if owner_id:
            items = MetadataService.query_by_owner(owner_id)
        else:
            items = MetadataService.query_by_category(category)
        return items
    except Exception as e:
        logger.error(f"Error querying images: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to query image metadata records.")


# Task 1.3: View / Download Image (GET Presigned URL)
@app.get(
    "/api/v1/images/{owner_id}/{image_id}/download",
    response_model=DownloadResponse,
    status_code=status.HTTP_200_OK,
    tags=["Image Management"],
    summary="Task 1.3: Get secure view/download URL",
    response_description="Returns a temporary GET presigned S3 download URL."
)
def get_image_download_url(owner_id: str, image_id: str):
    """
    Retrieves image metadata and generates a secure, short-lived GET presigned URL for direct viewing/downloading.
    """
    metadata = MetadataService.get_image(owner_id=owner_id, image_id=image_id)
    if not metadata or metadata.get("status") == "PENDING_DELETE":
        raise HTTPException(status_code=404, detail="Requested image was not found or has been deleted.")

    try:
        presigned_url = StorageService.generate_download_url(s3_key=metadata["s3_key"])
        return {"image_id": image_id, "download_url": presigned_url}
    except Exception as e:
        logger.error(f"Error generating download URL: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate secure download URL.")


# Task 1.4: Delete Image (Soft Delete + Async SQS Hard Delete)
@app.delete(
    "/api/v1/images/{owner_id}/{image_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Image Management"],
    summary="Task 1.4: Asynchronously delete an image",
    response_description="Marks item as soft-deleted and enqueues job for SQS worker hard purge."
)
def delete_image(owner_id: str, image_id: str):
    """
    Soft-deletes the image metadata in DynamoDB (`PENDING_DELETE`) for instant API read exclusion,
    and dispatches a message to SQS for background S3 and DynamoDB hard deletion.
    """
    metadata = MetadataService.get_image(owner_id=owner_id, image_id=image_id)
    if not metadata or metadata.get("status") == "PENDING_DELETE":
        raise HTTPException(status_code=404, detail="Requested image does not exist or is already deleted.")

    try:
        MetadataService.soft_delete_and_queue(
            owner_id=owner_id,
            image_id=image_id,
            s3_key=metadata["s3_key"]
        )
        return {"message": "Image deletion initiated successfully.", "image_id": image_id}
    except Exception as e:
        logger.error(f"Error initiating deletion: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to queue image deletion task.")