import json
from app.services.storage_service import StorageService


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
        # 1. Generate Upload Presigned URL
        if http_method == "POST" and path == "/images/upload-url":
            body = json.loads(event.get("body", "{}"))
            required = ["user_id", "file_name", "category", "tag"]
            if not all(k in body for k in required):
                return build_response(
                    400, {"error": f"Missing parameters. Required: {required}"}
                )

            result = StorageService.generate_upload_url(
                user_id=body["user_id"],
                file_name=body["file_name"],
                category=body["category"],
                tag=body["tag"],
            )
            return build_response(200, result)

        # 2. List Images (Supports category and tag filters)
        elif http_method == "GET" and path == "/images":
            category = query_params.get("category")
            tag = query_params.get("tag")
            items = StorageService.list_images(category=category, tag=tag)
            return build_response(200, {"images": items, "count": len(items)})

        # 3. View / Download Image
        elif http_method == "GET" and path.startswith("/images/"):
            image_id = path.split("/")[-1]
            data = StorageService.get_download_url(image_id)
            if not data:
                return build_response(404, {"error": "Image not found"})
            return build_response(200, data)

        # 4. Delete Image
        elif http_method == "DELETE" and path.startswith("/images/"):
            image_id = path.split("/")[-1]
            success = StorageService.delete_image(image_id)
            if not success:
                return build_response(404, {"error": "Image not found"})
            return build_response(
                200, {"message": f"Image {image_id} deleted successfully"}
            )

        return build_response(404, {"error": "Route not found"})

    except Exception as e:
        return build_response(500, {"error": str(e)})
