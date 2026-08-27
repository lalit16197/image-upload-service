import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas import (
    CompleteUploadRequest,
    DownloadResponse,
    ImageItemResponse,
    InitiateUploadRequest,
    MessageResponse,
    UploadResponse,
)
from app.services.metadata_service import MetadataService
from app.services.storage_service import StorageService

logger = logging.getLogger("api_images")
router = APIRouter(prefix="/images", tags=["Image Management"])


@router.post(
    "/upload-url",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Task 1.1: Initiate S3 Presigned Multipart Upload",
    response_description="Returns presigned multipart URLs. Metadata is written after asynchronous validation.",
)
def initiate_image_upload(payload: InitiateUploadRequest):
    try:
        return StorageService.initiate_multipart_upload(
            user_id=payload.owner_id,
            file_name=payload.file_name,
            total_parts=payload.total_parts,
            category=payload.category,
            tags=payload.tags,
            content_type=payload.content_type,
            caption=payload.caption,
        )
    except Exception as exc:
        logger.error("Error initiating upload: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to initialize image upload session.",
        ) from exc


@router.post(
    "/upload-complete",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Complete multipart upload and trigger quarantine validation",
)
def complete_image_upload(payload: CompleteUploadRequest):
    try:
        result = StorageService.complete_multipart_upload(
            s3_key=payload.s3_key,
            upload_id=payload.upload_id,
            parts=[part.model_dump() for part in payload.parts],
        )
        return {
            "message": "Upload completed; validation is processing asynchronously.",
            "s3_key": result["Key"],
        }
    except Exception as exc:
        logger.exception("Error completing multipart upload")
        raise HTTPException(
            status_code=500,
            detail="Failed to complete image upload.",
        ) from exc


@router.get(
    "",
    response_model=List[ImageItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Task 1.2: List active images with search filters",
)
def list_images(
    owner_id: Optional[str] = Query(
        None, description="Filter images by Owner ID"
    ),
    category: Optional[str] = Query(
        None, description="Filter images by Category"
    ),
    tags: Optional[str] = Query(
        None,
        description="Comma-separated tags; all tags must match",
    ),
    tag: Optional[str] = Query(None, include_in_schema=False),
    filename_prefix: Optional[str] = Query(
        None, description="Filename prefix, used with tag"
    ),
):
    if not owner_id and not category and not tags and not tag:
        raise HTTPException(
            status_code=400,
            detail="At least one search filter parameter ('owner_id', 'category', or 'tag') must be specified.",
        )

    try:
        return MetadataService.list_images(
            owner_id=owner_id,
            category=category,
            tags=tags if tags is not None else tag,
            filename_prefix=filename_prefix,
        )
    except Exception as exc:
        logger.error("Error querying images: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to query image metadata records.",
        ) from exc


@router.get(
    "/{owner_id}/{image_id}/download",
    response_model=DownloadResponse,
    status_code=status.HTTP_200_OK,
    summary="Task 1.3: Get secure view/download URL",
)
def get_image_download_url(owner_id: str, image_id: str):
    metadata = MetadataService.get_image(owner_id=owner_id, image_id=image_id)
    if not metadata or metadata.get("status") == "PENDING_DELETE":
        raise HTTPException(
            status_code=404,
            detail="Requested image was not found or has been deleted.",
        )

    try:
        presigned_url = StorageService.generate_download_url(
            s3_key=metadata["s3_key"]
        )
        return {"image_id": image_id, "download_url": presigned_url}
    except Exception as exc:
        logger.error("Error generating download URL: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate secure download URL.",
        ) from exc


@router.delete(
    "/{owner_id}/{image_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Task 1.4: Asynchronously delete an image",
)
def delete_image(owner_id: str, image_id: str):
    metadata = MetadataService.get_image(owner_id=owner_id, image_id=image_id)
    if not metadata or metadata.get("status") == "PENDING_DELETE":
        raise HTTPException(
            status_code=404,
            detail="Requested image does not exist or is already deleted.",
        )

    try:
        MetadataService.soft_delete_and_queue(
            owner_id=owner_id,
            image_id=image_id,
            s3_key=metadata["s3_key"],
        )
        return {
            "message": "Image deletion initiated successfully.",
            "image_id": image_id,
        }
    except Exception as exc:
        logger.error("Error initiating deletion: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to queue image deletion task.",
        ) from exc
