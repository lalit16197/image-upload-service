from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
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
        "description": "Core operations for presigned multipart upload generation, GSI-filtered querying, viewing, and async deletion.",
    },
]

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Instagram Scalable Image Upload & Metadata Service",
    description="""
## Cloud-Native Media Pipeline API

Supports direct-to-S3 presigned multipart uploads, single-table DynamoDB index lookups, 
and non-blocking asynchronous hard purging using AWS SQS.
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
    total_parts: int = Field(1, example=1, description="Number of multipart upload parts requested")

class PartUrlItem(BaseModel):
    part_number: int
    upload_url: str

class UploadResponse(BaseModel):
    image_id: str
    upload_id: str
    s3_key: str
    part_urls: List[PartUrlItem]

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

@app.post(
    "/api/v1/images/upload-url",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Image Management"],
    summary="Task 1.1: Initiate S3 Presigned Multipart Upload",
    response_description="Returns S3 multipart upload URLs and saves initial metadata to DynamoDB."
)
def initiate_image_upload(payload: InitiateUploadRequest):
    """
    Generates presigned S3 multipart upload links and initializes 
    the metadata lifecycle in DynamoDB with AVAILABLE status.
    """
    try:
        # Call storage service using user_id and total_parts
        upload_data = StorageService.initiate_multipart_upload(
            user_id=payload.owner_id,
            file_name=payload.file_name,
            total_parts=payload.total_parts
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
        raise HTTPException(status_code=500, detail=f"Failed to initialize image upload session: {str(e)}")


@app.get(
    "/api/v1/images",
    response_model=List[ImageItemResponse],
    status_code=status.HTTP_200_OK,
    tags=["Image Management"],
    summary="Task 1.2: List active images with search filters"
)
def list_images(
    owner_id: Optional[str] = Query(None, description="Filter images by Owner ID (uses GSI1)"),
    category: Optional[str] = Query(None, description="Filter images by Category (uses GSI2)")
):
    if not owner_id and not category:
        raise HTTPException(
            status_code=400, 
            detail="At least one search filter parameter ('owner_id' or 'category') must be specified."
        )

    try:
        if owner_id:
            return MetadataService.query_by_owner(owner_id)
        else:
            return MetadataService.query_by_category(category)
    except Exception as e:
        logger.error(f"Error querying images: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to query image metadata records.")


@app.get(
    "/api/v1/images/{owner_id}/{image_id}/download",
    response_model=DownloadResponse,
    status_code=status.HTTP_200_OK,
    tags=["Image Management"],
    summary="Task 1.3: Get secure view/download URL"
)
def get_image_download_url(owner_id: str, image_id: str):
    metadata = MetadataService.get_image(owner_id=owner_id, image_id=image_id)
    if not metadata or metadata.get("status") == "PENDING_DELETE":
        raise HTTPException(status_code=404, detail="Requested image was not found or has been deleted.")

    try:
        presigned_url = StorageService.generate_download_url(s3_key=metadata["s3_key"])
        return {"image_id": image_id, "download_url": presigned_url}
    except Exception as e:
        logger.error(f"Error generating download URL: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate secure download URL.")


@app.delete(
    "/api/v1/images/{owner_id}/{image_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Image Management"],
    summary="Task 1.4: Asynchronously delete an image"
)
def delete_image(owner_id: str, image_id: str):
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