from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI(title="M365 Risk Validation Lab", docs_url=None, redoc_url=None)
INDEX = Path(__file__).with_name("index.html")


@app.get("/health/live")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(INDEX)
