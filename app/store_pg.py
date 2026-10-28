"""Postgres + pgvector backend (set VECTOR_BACKEND=pgvector and DATABASE_URL)."""
import hashlib
import time

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from .config import settings
from .embed import chunk, embed
from .scraper import Doc

_ready = False


def _conn() -> psycopg.Connection:
    global _ready
    conn = psycopg.connect(settings.database_url, autocommit=True)
    if not _ready:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        dim = len(embed(["dimension probe"])[0])
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id text PRIMARY KEY, url text NOT NULL, title text, category text,
                source text, content_hash text, chunk int, ingested_at bigint,
                text text NOT NULL, embedding vector({dim}) NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS chunks_url_idx ON chunks (url)")
        conn.execute("CREATE INDEX IF NOT EXISTS chunks_source_idx ON chunks (source)")
        conn.execute("CREATE INDEX IF NOT EXISTS chunks_emb_idx ON chunks "
                     "USING hnsw (embedding vector_cosine_ops)")
        _ready = True
    register_vector(conn)
    return conn


def upsert_doc(doc: Doc) -> str:
    pieces = chunk(doc.text)
    if not pieces:
        return "unchanged"
    with _conn() as conn:
        row = conn.execute("SELECT content_hash FROM chunks WHERE url=%s LIMIT 1", (doc.url,)).fetchone()
        if row and row[0] == doc.content_hash:
            return "unchanged"
        status = "updated" if row else "new"
        embs = embed(pieces)
        uid = hashlib.sha256(doc.url.encode()).hexdigest()[:12]
        now = int(time.time())
        with conn.transaction():
            conn.execute("DELETE FROM chunks WHERE url=%s", (doc.url,))
            for i, (p, e) in enumerate(zip(pieces, embs)):
                conn.execute(
                    "INSERT INTO chunks (id,url,title,category,source,content_hash,chunk,ingested_at,text,embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (f"{uid}-{doc.content_hash[:12]}-{i}", doc.url, doc.title, doc.category,
                     doc.source, doc.content_hash, i, now, p, np.array(e)))
    return status


def prune_source(source: str, keep_urls: set[str]) -> int:
    with _conn() as conn:
        rows = conn.execute("SELECT DISTINCT url FROM chunks WHERE source=%s", (source,)).fetchall()
        stale = {r[0] for r in rows} - keep_urls
        for u in stale:
            conn.execute("DELETE FROM chunks WHERE url=%s", (u,))
    return len(stale)


def search(query: str, k: int = 5, category: str | None = None) -> list[dict]:
    q = np.array(embed([query])[0])
    with _conn() as conn:
        rows = conn.execute(
            "SELECT text,title,url,category,source,content_hash,chunk,ingested_at,"
            "1-(embedding <=> %s) AS score FROM chunks "
            "WHERE (%s::text IS NULL OR category=%s) ORDER BY embedding <=> %s LIMIT %s",
            (q, category, category, q, k)).fetchall()
    keys = ["text", "title", "url", "category", "source", "content_hash", "chunk", "ingested_at"]
    return [{**dict(zip(keys, r[:8])), "score": round(float(r[8]), 4)} for r in rows]


def stats() -> dict:
    with _conn() as conn:
        n = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    return {"backend": "pgvector", "chunks": n}
