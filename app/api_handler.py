import json
from app.services.storage_service import StorageService
from app.services.metadata_service import MetadataService


def build_response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def handler(event, context):
    http_method = event.get("httpMethod")
    path = event.get("path", "")
    query_params = event.get("queryStringParameters") or {}

    try:
        # 1. Generate Upload Presigned URL (Multipart support)
        if http_method == "POST" and path == "/images/upload-url":
            body = json.loads(event.get("body", "{}"))
            required = ["user_id", "file_name"]
            if not all(k in body for k in required):
                return build_response(
                    400, {"error": f"Missing parameters. Required: {required}"}
                )

            # Calls StorageService's correct multipart generation function
            result = StorageService.initiate_multipart_upload(
                user_id=body["user_id"],
                file_name=body["file_name"],
                total_parts=body.get("total_parts", 1)
            )
            return build_response(200, result)

        # 2. List Images (Supports category filter via MetadataService)
        elif http_method == "GET" and path == "/images":
            category = query_params.get("category")
            owner_id = query_params.get("owner_id")
            
            if category:
                items = MetadataService.list_images_by_category(category)
            elif owner_id:
                items = MetadataService.list_images_by_owner(owner_id)
            else:
                items = [] # Or a general list method if defined
                
            return build_response(200, {"images": items, "count": len(items)})

        # 3. View / Download Image (Generates presigned get URL)
        elif http_method == "GET" and path.startswith("/images/"):
            # Expects path like /images/{owner_id}/{image_id} or just looks up record
            parts = path.split("/")
            if len(parts) >= 4:
                owner_id = parts[2]
                image_id = parts[3]
                meta = MetadataService.get_image(owner_id, image_id)
                if not meta:
                    return build_response(404, {"error": "Image not found"})
                
                download_url = StorageService.generate_download_url(meta["s3_key"])
                return build_response(200, {"download_url": download_url, "metadata": meta})
            
            return build_response(400, {"error": "Invalid path structure for image lookup"})

        # 4. Delete Image (Triggers soft delete + SQS delete worker)
        elif http_method == "DELETE" and path.startswith("/images/"):
            parts = path.split("/")
            if len(parts) >= 4:
                owner_id = parts[2]
                image_id = parts[3]
                
                # Fetch meta to grab the s3_key first
                meta = MetadataService.get_image(owner_id, image_id)
                if not meta:
                    return build_response(404, {"error": "Image not found"})

                MetadataService.soft_delete_and_queue(
                    owner_id=owner_id, 
                    image_id=image_id, 
                    s3_key=meta["s3_key"]
                )
                return build_response(
                    200, {"message": f"Image {image_id} marked for deletion and queued successfully"}
                )

            return build_response(400, {"error": "Invalid delete path structure"})

        return build_response(404, {"error": "Route not found"})

    except Exception as e:
        return build_response(500, {"error": str(e)})