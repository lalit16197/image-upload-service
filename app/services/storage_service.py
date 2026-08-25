import uuid
from app.config import settings
from app.core.aws_clients import s3_client


class StorageService:

    @staticmethod
    def initiate_multipart_upload(user_id: str, file_name: str, total_parts: int = 1) -> dict:
        """Generates presigned URLs for multi-part S3 upload."""
        image_id = str(uuid.uuid4())
        s3_key = f"uploads/{user_id}/{image_id}/{file_name}"

        mpu = s3_client.create_multipart_upload(
            Bucket=settings.S3_BUCKET_NAME, 
            Key=s3_key
        )
        upload_id = mpu["UploadId"]

        part_urls = []
        for part_num in range(1, total_parts + 1):
            url = s3_client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": settings.S3_BUCKET_NAME,
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
    def generate_download_url(s3_key: str, expires_in: int = 3600) -> str:
        """Generates a temporary presigned download URL for an S3 object."""
        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    @staticmethod
    def delete_s3_object(s3_key: str) -> None:
        """Permanently purges an object from S3 bucket."""
        s3_client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)