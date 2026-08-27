from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.images import router as image_router

tags_metadata = [
    {
        "name": "Image Management",
        "description": "Quarantined multipart uploads, indexed metadata search, secure downloads, and asynchronous deletion.",
    },
]

app = FastAPI(
    title="Instagram Scalable Image Upload & Metadata Service",
    description="""
## Cloud-Native Media Pipeline API

Supports direct-to-S3 presigned multipart uploads, single-table DynamoDB index lookups,
and non-blocking asynchronous hard purging using AWS SQS.
    """,
    version="1.0.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(image_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse("app/static/index.html")
