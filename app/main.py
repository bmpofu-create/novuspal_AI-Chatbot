import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import SOURCES, settings
from . import ingest, store
from .embed import embed
from .rag import runtime_info, stream_chat, warm_model

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("novuspal")


def _warm_embed() -> None:
    try:
        embed(["library hours"])
    except Exception:
        log.exception("embedding warmup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm_embed, daemon=True).start()
    threading.Thread(target=warm_model, daemon=True).start()
    sched = ingest.start_scheduler()
    yield
    sched.shutdown(wait=False)


app = FastAPI(title="NovusPal API", version="0.3.0", lifespan=lifespan)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(
        Path(__file__).parent / "static" / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


def require_admin(x_api_key: str = Header(default="")):
    if x_api_key != settings.admin_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    category: str | None = None
    top_k: int = Field(default=4, ge=1, le=8)
    history: list[Turn] = Field(default_factory=list, max_length=8)


@app.get("/health")
def health():
    return {"status": "ok", **store.stats(), **runtime_info(), "last_runs": ingest.last_runs}


@app.get("/sources")
def sources():
    return [
        {
            "name": s.name,
            "category": s.category,
            "kind": s.kind,
            "urls": s.urls,
            "refresh_minutes": s.refresh_minutes,
        }
        for s in SOURCES
    ]


@app.get("/search")
def search(q: str, k: int = 5, category: str | None = None):
    return store.search(q, k, category)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/chat")
def chat(body: ChatIn):
    def generate():
        try:
            for event in stream_chat(body.message, body.category, body.top_k, body.history):
                yield _sse(event)
        except Exception:
            log.exception("chat failed")
            yield _sse({
                "type": "error",
                "text": "The local model could not answer. Please try again.",
            })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ingest/{source_name}", dependencies=[Depends(require_admin)])
def ingest_one(source_name: str):
    src = next((s for s in SOURCES if s.name == source_name), None)
    if not src:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown source")
    return ingest.run_source(src)


@app.post("/ingest", dependencies=[Depends(require_admin)])
def ingest_all():
    return {s.name: ingest.run_source(s) for s in SOURCES}
