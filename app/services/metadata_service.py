import json
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key
from app.config import settings
from app.core.aws_clients import table, sqs_client


class MetadataService:

    @staticmethod
    def save_metadata(
        image_id: str,
        user_id: str,
        category: str,
        tag: str,
        filename: str,
        s3_key: str,
        size_bytes: int = 0
    ) -> dict:
        """Saves image item metadata to DynamoDB using Single-Table Design."""
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "PK": f"OWNER#{user_id}",
            "SK": f"IMAGE#{image_id}",
            "GSI1PK": f"CATEGORY#{category}",
            "GSI1SK": f"CREATED#{now}",
            "image_id": image_id,
            "user_id": user_id,
            "category": category,
            "tag": tag,
            "filename": filename,
            "s3_key": s3_key,
            "size_bytes": size_bytes,
            "status": "AVAILABLE",
            "created_at": now,
        }
        table.put_item(Item=item)
        return item

    @staticmethod
    def get_image(user_id: str, image_id: str) -> dict | None:
        """Fetches a specific image by primary key."""
        res = table.get_item(Key={"PK": f"OWNER#{user_id}", "SK": f"IMAGE#{image_id}"})
        item = res.get("Item")
        if item and item.get("status") == "AVAILABLE":
            return item
        return None

    @staticmethod
    def list_images_by_owner(user_id: str) -> list[dict]:
        """Lists active images owned by a user."""
        res = table.query(
            KeyConditionExpression=Key("PK").eq(f"OWNER#{user_id}") & Key("SK").begins_with("IMAGE#")
        )
        return [item for item in res.get("Items", []) if item.get("status") == "AVAILABLE"]

    @staticmethod
    def list_images_by_category(category: str) -> list[dict]:
        """Queries images matching a category using Global Secondary Index (GSI1)."""
        res = table.query(
            IndexName="GSI1Index",
            KeyConditionExpression=Key("GSI1PK").eq(f"CATEGORY#{category}")
        )
        return [item for item in res.get("Items", []) if item.get("status") == "AVAILABLE"]

    @staticmethod
    def soft_delete_and_queue(user_id: str, image_id: str, s3_key: str) -> bool:
        """Marks metadata as PENDING_DELETE and enqueues async removal task into SQS."""
        pk = f"OWNER#{user_id}"
        sk = f"IMAGE#{image_id}"

        # 1. Immediate soft delete in DynamoDB
        table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET #st = :val",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":val": "PENDING_DELETE"},
        )

        # 2. Asynchronous job enqueue
        payload = {
            "action": "DELETE_IMAGE",
            "pk": pk,
            "sk": sk,
            "s3_key": s3_key,
            "image_id": image_id,
        }
        sqs_client.send_message(
            QueueUrl=settings.DELETE_QUEUE_URL,
            MessageBody=json.dumps(payload),
        )
        return True

    @staticmethod
    def hard_delete_metadata(pk: str, sk: str) -> None:
        """Permanently purges metadata record from DynamoDB."""
        table.delete_item(Key={"PK": pk, "SK": sk})