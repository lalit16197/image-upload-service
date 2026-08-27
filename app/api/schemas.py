from typing import List, Optional

from pydantic import BaseModel, Field


class InitiateUploadRequest(BaseModel):
    owner_id: str = Field(
        ...,
        description="Unique identifier of the image owner",
        json_schema_extra={"example": "user_mario_42"},
    )
    file_name: str = Field(
        ...,
        description="Original filename of the asset",
        json_schema_extra={"example": "vacation.jpg"},
    )
    content_type: str = Field(
        "image/jpeg",
        description="MIME content type",
        json_schema_extra={"example": "image/jpeg"},
    )
    category: str = Field(
        "general",
        description="Category of the image",
        json_schema_extra={"example": "travel"},
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Tags used for indexed search",
        json_schema_extra={"example": ["beach", "summer"]},
    )
    caption: Optional[str] = Field(
        None,
        description="Optional text description",
        json_schema_extra={"example": "Summer in Rome"},
    )
    total_parts: int = Field(
        1,
        ge=1,
        le=10000,
        description="Number of multipart upload parts requested",
        json_schema_extra={"example": 1},
    )


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
    tags: List[str] = Field(default_factory=list)
    tag: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: int = 0


class DownloadResponse(BaseModel):
    image_id: str
    download_url: str


class MessageResponse(BaseModel):
    message: str
    image_id: str
