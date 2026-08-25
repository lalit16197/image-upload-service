import os


class Settings:
    AWS_REGION: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    ENDPOINT_URL: str | None = os.getenv("AWS_ENDPOINT_URL")  # Set for LocalStack, None in AWS production
    PUBLIC_ENDPOINT_URL: str = os.getenv("PUBLIC_ENDPOINT_URL", "http://localhost:4566")

    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "instagram-images-bucket")
    QUARANTINE_BUCKET_NAME: str = os.getenv("QUARANTINE_BUCKET_NAME", "instagram-images-quarantine")
    MULTIPART_PART_SIZE_BYTES: int = int(os.getenv("MULTIPART_PART_SIZE_BYTES", str(8 * 1024 * 1024)))
    DYNAMODB_TABLE_NAME: str = os.getenv("DYNAMODB_TABLE_NAME", "ImagesMetadata")
    
    # SQS Queues
    DELETE_QUEUE_URL: str = os.getenv(
        "DELETE_QUEUE_URL", 
        "http://127.0.0.1:4566/000000000000/image-delete-queue"
    )
    UPLOAD_QUEUE_URL: str = os.getenv(
        "UPLOAD_QUEUE_URL", 
        "http://127.0.0.1:4566/000000000000/image-upload-queue"
    )


settings = Settings()