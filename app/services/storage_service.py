import uuid
from app.config import settings
from app.core.aws_clients import presign_s3_client, s3_client
from app.services.metadata_service import MetadataService


class StorageService:

    @staticmethod
    def initiate_multipart_upload(
        user_id: str,
        file_name: str,
        total_parts: int = 1,
        category: str | None = None,
        tag: str | None = None,
        tags: list[str] | None = None,
        content_type: str | None = None,
        caption: str | None = None,
    ) -> dict:
        """Generates presigned URLs for multi-part S3 upload."""
        if total_parts < 1 or total_parts > 10000:
            raise ValueError("total_parts must be between 1 and 10000")
        image_id = str(uuid.uuid4())
        s3_key = f"uploads/{user_id}/{image_id}/{file_name}"

        metadata = {
            "owner_id": user_id,
            "image_id": image_id,
            "filename": file_name,
            "tags": ",".join(
                value.strip()
                for value in (tags if tags is not None else ([tag] if tag else []))
                if value and value.strip()
            ),
        }
        for name, value in (("category", category), ("caption", caption)):
            if value is not None:
                metadata[name] = value

        mpu = s3_client.create_multipart_upload(
            Bucket=settings.QUARANTINE_BUCKET_NAME,
            Key=s3_key,
            ContentType=content_type or "application/octet-stream",
            Metadata=metadata,
        )
        upload_id = mpu["UploadId"]

        part_urls = []
        for part_num in range(1, total_parts + 1):
            url = presign_s3_client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": settings.QUARANTINE_BUCKET_NAME,
                    "Key": s3_key,
                    "UploadId": upload_id,
                    "PartNumber": part_num,
                },
                ExpiresIn=3600,
            )
            part_urls.append({"part_number": part_num, "upload_url": url})

        return {
            "image_id": image_id,
            "upload_id": upload_id,
            "s3_key": s3_key,
            "part_urls": part_urls,
        }

    @staticmethod
    def complete_multipart_upload(s3_key: str, upload_id: str, parts: list[dict]) -> dict:
        """Completes the client-uploaded multipart object."""
        return s3_client.complete_multipart_upload(
            Bucket=settings.QUARANTINE_BUCKET_NAME,
            Key=s3_key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    @staticmethod
    def save_metadata(*args, **kwargs) -> dict:
        """Backward-compatible facade for the metadata service."""
        return MetadataService.save_metadata(*args, **kwargs)

    @staticmethod
    def list_images(**filters) -> list[dict]:
        """Backward-compatible facade for filtered metadata queries."""
        return MetadataService.list_images(**filters)

    @staticmethod
    def delete_image_async(user_id: str, image_id: str) -> bool:
        metadata = MetadataService.get_image(user_id, image_id)
        if not metadata:
            return False
        return MetadataService.soft_delete_and_queue(user_id, image_id, metadata["s3_key"])

    @staticmethod
    def generate_download_url(s3_key: str, expires_in: int = 3600) -> str:
        """Generates a temporary presigned download URL for an S3 object."""
        return presign_s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    @staticmethod
    def delete_s3_object(s3_key: str) -> None:
        """Permanently purges an object from S3 bucket."""
        s3_client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)


def delete_worker_handler(event, context):
    """Compatibility entrypoint for older integrations."""
    from app.workers.delete_worker import delete_worker_handler as handler
    return handler(event, context)