import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from boto3.dynamodb.conditions import Attr, Key
from app.config import settings
from app.core.aws_clients import table, sqs_client


class MetadataService:

    @staticmethod
    def save_metadata(image_id: str, *args, **kwargs) -> dict:
        """Saves image item metadata to DynamoDB using Single-Table Design."""
        if args:
            owner_id, category, tag, filename, s3_key, size_bytes = (
                list(args) + [None] * 6
            )[:6]
        else:
            owner_id = kwargs.get("owner_id") or kwargs.get("user_id")
            category = kwargs.get("category", "general")
            tag = kwargs.get("tag")
            filename = kwargs.get("filename")
            s3_key = kwargs.get("s3_key", "")
            size_bytes = kwargs.get("size_bytes", 0)
        caption = kwargs.get("caption")
        owner_id = owner_id or kwargs.get("user_id")
        if not owner_id:
            raise ValueError("owner_id is required")
        now = datetime.now(timezone.utc).isoformat()
        filename = filename or s3_key.rsplit("/", 1)[-1]
        
        item = {
            "PK": f"OWNER#{owner_id}",
            "SK": f"IMAGE#{image_id}",
            "GSI1PK": f"TAG#{tag or '_none'}",
            "GSI1SK": f"NAME#{filename}#{image_id}",
            "GSI2PK": f"CATEGORY#{category}",
            "GSI2SK": f"CREATED#{now}#{image_id}",
            "image_id": image_id,
            "owner_id": owner_id,
            "category": category,
            "caption": caption,
            "tag": tag,
            "filename": filename,
            "size_bytes": size_bytes,
            "s3_key": s3_key,
            "status": "AVAILABLE",
            "created_at": now,
        }
        
        table.put_item(Item=item)
        return item

    @staticmethod
    def get_image(owner_id: str, image_id: str) -> dict | None:
        """Fetches a specific image by primary key."""
        res = table.get_item(Key={"PK": f"OWNER#{owner_id}", "SK": f"IMAGE#{image_id}"})
        item = res.get("Item")
        if item and item.get("status") == "AVAILABLE":
            return item
        return None

    @staticmethod
    def _query(index_name, key_condition, filter_expression=None) -> list[dict]:
        items = []
        query_args = {
            "KeyConditionExpression": key_condition,
        }
        if index_name:
            query_args["IndexName"] = index_name
        if filter_expression is not None:
            query_args["FilterExpression"] = filter_expression
        while True:
            response = table.query(**query_args)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            query_args["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return [item for item in items if item.get("status") == "AVAILABLE"]

    @staticmethod
    def list_images_by_owner(owner_id: str) -> list[dict]:
        """Lists active images owned by a user."""
        return MetadataService._query(
            None,
            Key("PK").eq(f"OWNER#{owner_id}") & Key("SK").begins_with("IMAGE#"),
        )

    @staticmethod
    def list_images_by_category(category: str, tag: Optional[str] = None) -> list[dict]:
        """Queries images matching a category using Global Secondary Index (GSI1)."""
        kwargs = {
            "IndexName": "GSI2Index",
            "KeyConditionExpression": Key("GSI2PK").eq(f"CATEGORY#{category}"),
        }
        if tag:
            kwargs["FilterExpression"] = Attr("tag").eq(tag)
        return MetadataService._query(
            kwargs["IndexName"],
            kwargs["KeyConditionExpression"],
            kwargs.get("FilterExpression"),
        )

    @staticmethod
    def list_images_by_tag(tag: str, filename_prefix: Optional[str] = None) -> list[dict]:
        key_condition = Key("GSI1PK").eq(f"TAG#{tag}")
        if filename_prefix:
            key_condition &= Key("GSI1SK").begins_with(f"NAME#{filename_prefix}")
        return MetadataService._query("GSI1Index", key_condition)

    @staticmethod
    def list_images(**filters) -> list[dict]:
        owner_id = filters.get("owner_id") or filters.get("user_id")
        category = filters.get("category")
        tag = filters.get("tag")
        filename_prefix = filters.get("filename_prefix")
        if owner_id:
            items = MetadataService.list_images_by_owner(owner_id)
            if category:
                items = [item for item in items if item.get("category") == category]
            if tag:
                items = [item for item in items if item.get("tag") == tag]
            return items
        if category:
            return MetadataService.list_images_by_category(category, tag)
        if tag:
            return MetadataService.list_images_by_tag(tag, filename_prefix)
        return []

    query_by_owner = list_images_by_owner
    query_by_category = list_images_by_category

    @staticmethod
    def soft_delete_and_queue(
        owner_id: str | None = None,
        image_id: str = "",
        s3_key: str = "",
        user_id: str | None = None,
    ) -> bool:
        """Marks metadata as PENDING_DELETE and enqueues async removal task into SQS."""
        owner_id = owner_id or user_id
        if not owner_id:
            raise ValueError("owner_id is required")
        pk = f"OWNER#{owner_id}"
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