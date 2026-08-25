from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
        "description": "Quarantined multipart uploads, indexed metadata search, secure downloads, and asynchronous deletion.",
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
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse("app/static/index.html")

# --- Pydantic Request & Response Schemas ---
class InitiateUploadRequest(BaseModel):
    owner_id: str = Field(..., description="Unique identifier of the image owner",
                          json_schema_extra={"example": "user_mario_42"})
    file_name: str = Field(..., description="Original filename of the asset",
                           json_schema_extra={"example": "vacation.jpg"})
    content_type: str = Field("image/jpeg", description="MIME content type",
                              json_schema_extra={"example": "image/jpeg"})
    category: str = Field("general", description="Category tag used for GSI indexing",
                          json_schema_extra={"example": "travel"})
    tag: Optional[str] = Field(None, description="Tag used for indexed search",
                               json_schema_extra={"example": "beach"})
    caption: Optional[str] = Field(None, description="Optional text description",
                                   json_schema_extra={"example": "Summer in Rome"})
    total_parts: int = Field(1, ge=1, le=10000,
                             description="Number of multipart upload parts requested",
                             json_schema_extra={"example": 1})

class PartUrlItem(BaseModel):
    part_number: int
    upload_url: str

class UploadResponse(BaseModel):
    image_id: str
    upload_id: str
    s3_key: str
    part_urls: List[PartUrlItem]

class CompletePart(BaseModel):
    PartNumber: int = Field(..., ge=1)
    ETag: str

class CompleteUploadRequest(BaseModel):
    s3_key: str
    upload_id: str
    parts: List[CompletePart]

class ImageItemResponse(BaseModel):
    image_id: str
    owner_id: str
    category: str
    status: str
    s3_key: str
    created_at: str
    caption: Optional[str] = None
    tag: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: int = 0

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
    response_description="Returns presigned multipart URLs. Metadata is written after asynchronous validation."
)
def initiate_image_upload(payload: InitiateUploadRequest):
    """
    Generates presigned S3 multipart upload links. The upload worker later
    validates the object and persists its metadata.
    """
    try:
        # Call storage service using user_id and total_parts
        upload_data = StorageService.initiate_multipart_upload(
            user_id=payload.owner_id,
            file_name=payload.file_name,
            total_parts=payload.total_parts,
            category=payload.category,
            tag=payload.tag,
            content_type=payload.content_type,
            caption=payload.caption,
        )
        return upload_data
    except Exception as e:
        logger.error(f"Error initiating upload: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to initialize image upload session.")


@app.post(
    "/api/v1/images/upload-complete",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Image Management"],
    summary="Complete multipart upload and trigger quarantine validation",
)
def complete_image_upload(payload: CompleteUploadRequest):
    try:
        result = StorageService.complete_multipart_upload(
            s3_key=payload.s3_key,
            upload_id=payload.upload_id,
            parts=[part.dict() for part in payload.parts],
        )
        return {
            "message": "Upload completed; validation is processing asynchronously.",
            "s3_key": result["Key"],
        }
    except Exception:
        logger.exception("Error completing multipart upload")
        raise HTTPException(status_code=500, detail="Failed to complete image upload.")


@app.get(
    "/api/v1/images",
    response_model=List[ImageItemResponse],
    status_code=status.HTTP_200_OK,
    tags=["Image Management"],
    summary="Task 1.2: List active images with search filters"
)
def list_images(
    owner_id: Optional[str] = Query(None, description="Filter images by Owner ID (uses GSI1)"),
    category: Optional[str] = Query(None, description="Filter images by Category (uses GSI2)"),
    tag: Optional[str] = Query(None, description="Filter images by Tag (uses GSI1)"),
    filename_prefix: Optional[str] = Query(None, description="Filename prefix, used with tag"),
):
    if not owner_id and not category and not tag:
        raise HTTPException(
            status_code=400, 
            detail="At least one search filter parameter ('owner_id', 'category', or 'tag') must be specified."
        )

    try:
        return MetadataService.list_images(
            owner_id=owner_id,
            category=category,
            tag=tag,
            filename_prefix=filename_prefix,
        )
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