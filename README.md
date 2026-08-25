# image-upload-service
Event-driven microservice for image storage &amp; soft/hard deletion using FastAPI, LocalStack (S3, DynamoDB GSI, SQS), Docker Compose

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
