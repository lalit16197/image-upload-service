
---

## API Documentation & OpenAPI Specification

When the service container is running (`docker-compose up`), access interactive documentation at the following URLs:

* **Interactive Swagger UI:** `http://localhost:8000/docs`
* **ReDoc Documentation:** `http://localhost:8000/redoc`
* **Raw OpenAPI JSON Schema:** `http://localhost:8000/openapi.json`

### Exporting to Postman / Insomnia
1. Launch the service locally.
2. Download the raw OpenAPI schema from `http://localhost:8000/openapi.json`.
3. Open **Postman** -> Click **Import** -> Select `openapi.json` to generate an interactive request collection.
