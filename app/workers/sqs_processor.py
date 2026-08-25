import os
import time
import boto3
from app.config import settings
from app.workers.delete_worker import delete_worker_handler

# Determine credentials, region, and endpoint URL
aws_region = getattr(settings, "AWS_REGION", None) or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
endpoint_url = getattr(settings, "ENDPOINT_URL", None) or os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")

aws_access_key_id = getattr(settings, "AWS_ACCESS_KEY_ID", None) or os.getenv("AWS_ACCESS_KEY_ID", "test")
aws_secret_access_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None) or os.getenv("AWS_SECRET_ACCESS_KEY", "test")

# Instantiate SQS client directly using boto3
sqs_client = boto3.client(
    "sqs",
    endpoint_url=endpoint_url,
    region_name=aws_region,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)


def start_polling():
    queue_url = os.getenv("DELETE_QUEUE_URL") or getattr(
        settings, 
        "DELETE_QUEUE_URL", 
        "http://127.0.0.1:4566/000000000000/image-delete-queue"
    )
    
    print(f"[*] SQS Delete Worker active. Polling queue: {queue_url}")

    while True:
        try:
            response = sqs_client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=2,
            )
            messages = response.get("Messages", [])

            if messages:
                # Structure incoming SQS payload into standard event structure
                event = {
                    "Records": [
                        {"messageId": msg["MessageId"], "body": msg["Body"]}
                        for msg in messages
                    ]
                }

                # Delegate processing to the delete worker handler
                result = delete_worker_handler(event, None)
                failed_ids = {item["itemIdentifier"] for item in result.get("batchItemFailures", [])}

                # Remove successfully processed messages from SQS queue
                for msg in messages:
                    if msg["MessageId"] not in failed_ids:
                        sqs_client.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
            else:
                time.sleep(1)

        except Exception as err:
            print(f"[Worker Exception] {err}")
            time.sleep(2)


if __name__ == "__main__":
    start_polling()