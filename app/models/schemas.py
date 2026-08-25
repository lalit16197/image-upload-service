from pydantic import BaseModel, Field


class UploadInitiateRequest(BaseModel):
    user_id: str = Field(..., example="user_mario_42")
    file_name: str = Field(..., example="vacation.jpg")
    category: str = Field(..., example="travel")
    tag: str = Field(..., example="beach")
    total_parts: int = Field(default=1, ge=1, le=100)


class MultipartPartSpec(BaseModel):
    part_number: int
    upload_url: str


class UploadInitiateResponse(BaseModel):
    image_id: str
    upload_id: str
    s3_key: str
    part_urls: list[MultipartPartSpec]


class UploadCompletePart(BaseModel):
    PartNumber: int
    ETag: str


class UploadCompleteRequest(BaseModel):
    image_id: str
    user_id: str
    s3_key: str
    upload_id: str
    parts: list[UploadCompletePart]
    category: str
    tag: str
    filename: str
    size_bytes: int = 0


class ImageMetadataResponse(BaseModel):
    image_id: str
    user_id: str
    category: str
    tag: str
    filename: str
    s3_key: str
    size_bytes: int
    status: str
    created_at: str
    download_url: str | None = None