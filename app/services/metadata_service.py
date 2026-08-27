import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from boto3.dynamodb.conditions import Attr, Key
from app.config import settings
from app.core.aws_clients import table, sqs_client


class MetadataService:

    @staticmethod
    def _normalize_tags(tags=None, tag=None) -> list[str]:
        values = tags if tags is not None else ([tag] if tag else [])
        if isinstance(values, str):
            values = values.split(",")
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))

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
        tags = MetadataService._normalize_tags(kwargs.get("tags"), tag)
        owner_id = owner_id or kwargs.get("user_id")
        if not owner_id:
            raise ValueError("owner_id is required")
        now = datetime.now(timezone.utc).isoformat()
        filename = filename or s3_key.rsplit("/", 1)[-1]
        
        item = {
            "PK": f"OWNER#{owner_id}",
            "SK": f"IMAGE#{image_id}",
            "GSI2PK": f"CATEGORY#{category}",
            "GSI2SK": f"CREATED#{now}#{image_id}",
            "image_id": image_id,
            "owner_id": owner_id,
            "category": category,
            "caption": caption,
            "tag": tags[0] if tags else None,
            "tags": tags,
            "filename": filename,
            "size_bytes": size_bytes,
            "s3_key": s3_key,
            "status": "AVAILABLE",
            "created_at": now,
        }
        
        table.put_item(Item=item)
        for indexed_tag in tags:
            table.put_item(Item={
                "PK": item["PK"],
                "SK": f"TAG#{indexed_tag}#IMAGE#{image_id}",
                "GSI1PK": f"TAG#{indexed_tag}",
                "GSI1SK": f"NAME#{filename}#{image_id}",
                "GSI3PK": f"CATEGORY#{category}#TAG#{indexed_tag}",
                "GSI3SK": f"CREATED#{now}#{image_id}",
                "image_id": image_id,
                "owner_id": owner_id,
                "category": category,
                "tags": tags,
                "tag": indexed_tag,
                "filename": filename,
                "size_bytes": size_bytes,
                "s3_key": s3_key,
                "status": "AVAILABLE",
                "created_at": now,
            })
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
        return [
            item for item in MetadataService._query_all(index_name, key_condition, filter_expression)
            if item.get("status") == "AVAILABLE"
        ]

    @staticmethod
    def _query_all(index_name, key_condition, filter_expression=None) -> list[dict]:
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
        return items

    @staticmethod
    def list_images_by_owner(owner_id: str) -> list[dict]:
        """Lists active images owned by a user."""
        return MetadataService._query(
            None,
            Key("PK").eq(f"OWNER#{owner_id}") & Key("SK").begins_with("IMAGE#"),
        )

    @staticmethod
    def list_images_by_category(category: str, tag: Optional[str] = None) -> list[dict]:
        """Queries images matching a category using the category index."""
        if tag:
            return MetadataService.list_images_by_category_and_tags(category, tag)
        kwargs = {
            "IndexName": "GSI2Index",
            "KeyConditionExpression": Key("GSI2PK").eq(f"CATEGORY#{category}"),
        }
        items = MetadataService._query(
            kwargs["IndexName"],
            kwargs["KeyConditionExpression"],
        )
        return items

    @staticmethod
    def list_images_by_category_and_tags(category: str, tags) -> list[dict]:
        """Queries exact category/tag combinations through GSI3."""
        requested_tags = MetadataService._normalize_tags(tags)
        if not requested_tags:
            return MetadataService.list_images_by_category(category)

        results = []
        for requested_tag in requested_tags:
            results.append(
                MetadataService._query(
                    "GSI3Index",
                    Key("GSI3PK").eq(
                        f"CATEGORY#{category}#TAG#{requested_tag}"
                    ),
                )
            )

        by_id = {item["image_id"]: item for item in results[0]}
        for items in results[1:]:
            ids = {item["image_id"] for item in items}
            by_id = {
                image_id: item
                for image_id, item in by_id.items()
                if image_id in ids
            }
        return list(by_id.values())

    @staticmethod
    def list_images_by_tag(tag: str, filename_prefix: Optional[str] = None) -> list[dict]:
        tags = MetadataService._normalize_tags(tag)
        if not tags:
            return []
        results = []
        for requested_tag in tags:
            key_condition = Key("GSI1PK").eq(f"TAG#{requested_tag}")
            if filename_prefix:
                key_condition &= Key("GSI1SK").begins_with(f"NAME#{filename_prefix}")
            results.append(MetadataService._query("GSI1Index", key_condition))
        by_id = {item["image_id"]: item for item in results[0]}
        for items in results[1:]:
            ids = {item["image_id"] for item in items}
            by_id = {image_id: item for image_id, item in by_id.items() if image_id in ids}
        return list(by_id.values())

    @staticmethod
    def _filter_tags(items: list[dict], tag: Optional[str]) -> list[dict]:
        requested = set(MetadataService._normalize_tags(tag))
        if not requested:
            return items
        return [
            item for item in items
            if requested.issubset(
                set(
                    item.get("tags")
                    or MetadataService._normalize_tags(item.get("tag"))
                )
            )
        ]

    @staticmethod
    def list_images(**filters) -> list[dict]:
        owner_id = filters.get("owner_id") or filters.get("user_id")
        category = filters.get("category")
        tag = filters.get("tag")
        tags = filters.get("tags")
        tag_query = tags if tags is not None else tag
        filename_prefix = filters.get("filename_prefix")
        if owner_id:
            items = MetadataService.list_images_by_owner(owner_id)
            if category:
                items = [item for item in items if item.get("category") == category]
            items = MetadataService._filter_tags(items, tag_query)
            return items
        if category:
            return MetadataService.list_images_by_category_and_tags(
                category, tag_query
            ) if tag_query else MetadataService.list_images_by_category(category)
        if tag_query:
            return MetadataService.list_images_by_tag(tag_query, filename_prefix)
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
        for item in MetadataService._query_all(None, Key("PK").eq(pk) & Key("SK").begins_with("TAG#")):
            if item.get("image_id") == image_id:
                table.update_item(
                    Key={"PK": pk, "SK": item["SK"]},
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
        for item in MetadataService._query(None, Key("PK").eq(pk) & Key("SK").begins_with("TAG#")):
            if item.get("image_id") == sk.removeprefix("IMAGE#"):
                table.delete_item(Key={"PK": pk, "SK": item["SK"]})