"""Local FastAPI server: REST API + static edit page (requirement 4).
Start with: dota serve   (or: python -m dota_assistant.ui.server)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dota_assistant.core.positions import normalize_position
from dota_assistant.db.database import connect, init_schema
from dota_assistant.db.repo import Repo

STATIC_DIR = Path(__file__).resolve().parent / "static"
app = FastAPI(title="dota:assistant", version="0.1.0")


def _repo() -> Repo:
    conn = connect()
    init_schema(conn)
    return Repo(conn)


class AdviceIn(BaseModel):
    hero: str
    position: str
    t_start_min: float
    t_end_min: float
    advice: str
    source: Optional[str] = "user"


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stats")
def stats():
    with _repo() as r:
        return r.stats()


@app.get("/api/advice")
def list_advice(hero: Optional[str] = None, position: Optional[str] = None):
    with _repo() as r:
        pos = normalize_position(position) if position else None
        return [dict(row) for row in r.list_advice(hero=hero, position=pos)]


@app.post("/api/advice")
def upsert_advice(body: AdviceIn):
    from dota_assistant.core.models import Advice

    pos = normalize_position(body.position)
    with _repo() as r:
        new_id = r.upsert_advice(
            Advice(
                hero=body.hero,
                position=pos,
                t_start_min=body.t_start_min,
                t_end_min=body.t_end_min,
                advice=body.advice,
                source=body.source,
            )
        )
    return {"id": new_id, "ok": True}


@app.delete("/api/advice/{advice_id}")
def delete_advice(advice_id: int):
    with _repo() as r:
        ok = r.delete_advice(advice_id)
    if not ok:
        raise HTTPException(404, "advice not found")
    return {"ok": True}


@app.get("/api/samples")
def list_samples(hero: Optional[str] = None, position: Optional[str] = None):
    with _repo() as r:
        pos = normalize_position(position) if position else None
        rows = r.samples_by_hero_position(hero or "", pos or "")
        return [r.sample_json(row) for row in rows]


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
