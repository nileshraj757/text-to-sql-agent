"""FastAPI: POST /ask, GET /health. Server-side limits: question length, row cap, timeout, rate limit, daily cap."""
from __future__ import annotations
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ..agent.dataset import MAX_FILE_BYTES, UploadError
from .service import AskService, load_samples

limiter = Limiter(key_func=get_remote_address)
state: dict = {}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: str | None = None
    dataset_id: str | None = None


class AskResponse(BaseModel):
    status: str
    message: str = ""
    sql: str | None = None
    assumptions: list[str] = []
    columns: list[str] = []
    rows: list[list] = []
    truncated: bool = False
    chart: dict | None = None
    explanation: dict | None = None
    attempts: list[dict] = []
    blocked_by: str | None = None
    mode: str = "live"
    latency_ms: int = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["svc"] = AskService()
    yield


app = FastAPI(title="Text-to-SQL Analytics Agent", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/health")
def health():
    return {"ok": True, "mode": state["svc"].mode}


@app.get("/samples")
def samples():
    return load_samples()


@app.post("/ask", response_model=AskResponse)
@limiter.limit("20/minute")
def ask(request: Request, body: AskRequest):
    return state["svc"].ask(body.question, body.session_id or request.client.host or uuid.uuid4().hex, body.dataset_id)


@app.post("/upload")
@limiter.limit("6/minute")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    data = []
    for f in files:
        blob = await f.read(MAX_FILE_BYTES + 1)
        data.append((f.filename or "file", blob))
    try:
        return state["svc"].create_dataset(data)
    except UploadError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/datasets/{dataset_id}/preview/{table}")
def preview(dataset_id: str, table: str):
    try:
        return state["svc"].dataset_preview(dataset_id, table)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown dataset or table")
