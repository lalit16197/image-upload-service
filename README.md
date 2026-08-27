# image-upload-service
Event-driven microservice for image storage &amp; soft/hard deletion using FastAPI, LocalStack (S3, DynamoDB GSI, SQS), Docker Compose

---

## Local Setup

### Prerequisites

Install the following tools:

* Git
* Docker Engine
* Docker Compose v2 (`docker compose`)
* Python 3.11 or newer (only needed for running tests outside Docker)

Confirm the installations:

```bash
git --version
docker --version
docker compose version
python3 --version
```

### Clone and enter the project

```bash
git clone https://github.com/lalit16197/image-upload-service.git
cd image-upload-service
```


### Start the complete local stack

The first command builds the API and worker images, starts LocalStack, and runs
the AWS resource initialization script. It creates S3 buckets, SQS queues,
DynamoDB indexes, and event notifications automatically.

```bash
docker compose up --build
```

Run the stack in the background:

```bash
docker compose up --build -d
```

Check service status and logs:

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f upload-worker
docker compose logs -f delete-worker
```

The LocalStack health check waits for the required buckets, queues, and
`ImagesMetadata` DynamoDB table before starting the API and workers.

### Open the local application

After the containers are healthy, open:

* Web UI: <http://localhost:8000/>
* Swagger UI: <http://localhost:8000/docs>
* ReDoc: <http://localhost:8000/redoc>
* OpenAPI JSON: <http://localhost:8000/openapi.json>

The upload flow is:

```text
POST /api/v1/images/upload-url
upload file parts directly to the returned S3 URLs
POST /api/v1/images/upload-complete
```

### Verify LocalStack resources

The following commands run inside the LocalStack container:

```bash
docker compose exec localstack awslocal s3 ls
docker compose exec localstack awslocal sqs list-queues
docker compose exec localstack awslocal dynamodb describe-table \
  --table-name ImagesMetadata
```

To inspect the configured indexes:

```bash
docker compose exec localstack awslocal dynamodb describe-table \
  --table-name ImagesMetadata \
  --query 'Table.GlobalSecondaryIndexes[].IndexName'
```

### Run tests locally

Create a virtual environment and install the project dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest -q
```

Run the unit test suite explicitly:

```bash
python -m pytest -q tests/
```

Run a specific test file:

```bash
python -m pytest -q tests/test_storage_service.py
```

Run one test by name:

```bash
python -m pytest -q tests/test_storage_service.py -k gsi3
```

### Stop and reset the local stack

Stop containers while preserving LocalStack data:

```bash
docker compose down
```

Stop containers and remove the local Docker volumes:

```bash
docker compose down -v
```

The repository also persists LocalStack state in `.localstack_data`. To start
with a completely clean local AWS state, stop the stack first, then remove
that project-local directory:

```bash
docker compose down
rm -rf .localstack_data
docker compose up --build
```

---

## API Documentation & OpenAPI Specification

### Event-driven upload architecture

1. `POST /api/v1/images/upload-url` creates an S3 multipart upload in the quarantine bucket and returns presigned part URLs. No DynamoDB record is written at this stage.
2. The client uploads 5-10 MB parts directly to S3 in parallel, then calls `POST /api/v1/images/upload-complete`.
3. S3 sends an `ObjectCreated` event to SQS. The upload Lambda validates the object magic bytes, copies valid images to the production bucket, and writes metadata to DynamoDB.
4. `GET /api/v1/images` queries the owner key, category GSI, or tag/name-prefix GSI. `DELETE` changes status to `PENDING_DELETE` and queues the purge worker.

The quarantine bucket aborts incomplete multipart uploads after 24 hours. The upload queue retries failed messages three times and then routes them to a DLQ.

### Web UI

Open `http://localhost:8000/` after starting Docker Compose. The UI uses the FastAPI endpoints to upload metadata and image parts, search by owner/category/tag, open a presigned download URL, and queue deletion.

For API-only smoke testing, use the generated OpenAPI page at `http://localhost:8000/docs`; the upload flow is `upload-url` -> direct S3 part uploads -> `upload-complete`.

When the service container is running (`docker-compose up`), access interactive documentation at the following URLs:

* **Interactive Swagger UI:** `http://localhost:8000/docs`
* **ReDoc Documentation:** `http://localhost:8000/redoc`
* **Raw OpenAPI JSON Schema:** `http://localhost:8000/openapi.json`

### Exporting to Postman / Insomnia
1. Launch the service locally.
2. Download the raw OpenAPI schema from `http://localhost:8000/openapi.json`.
3. Open **Postman** -> Click **Import** -> Select `openapi.json` to generate an interactive request collection.
