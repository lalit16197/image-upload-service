import time

import boto3

from app.config import settings
from app.workers.upload_worker import upload_worker_handler


def start_polling():
    sqs = boto3.client(
        "sqs",
        endpoint_url=settings.ENDPOINT_URL,
        region_name=settings.AWS_REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    queue_url = settings.UPLOAD_QUEUE_URL
    print("[*] Upload worker polling {}".format(queue_url), flush=True)

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=10,
                VisibilityTimeout=180,
            )
            messages = response.get("Messages", [])
            if not messages:
                continue

            event = {
                "Records": [
                    {"messageId": message["MessageId"], "body": message["Body"]}
                    for message in messages
                ]
            }
            result = upload_worker_handler(event, None)
            failed = {item["itemIdentifier"] for item in result.get("batchItemFailures", [])}
            for message in messages:
                if message["MessageId"] not in failed:
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=message["ReceiptHandle"],
                    )
        except Exception as error:
            print("[Upload worker exception] {}".format(error), flush=True)
            time.sleep(2)


if __name__ == "__main__":
    start_polling()
