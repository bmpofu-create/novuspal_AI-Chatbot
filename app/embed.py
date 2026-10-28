"""Local embeddings and chunking.

Chroma and pgvector only store and search vectors. They do not embed text,
so this module runs sentence-transformers on this machine. The same model
embeds pages during ingest and questions during search.
"""
import os
import threading

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from sentence_transformers import SentenceTransformer

from .config import settings

_model: SentenceTransformer | None = None
_init_lock = threading.Lock()


def embed(texts: list[str]) -> list[list[float]]:
    global _model
    if _model is None:
        with _init_lock:
            if _model is None:
                _model = SentenceTransformer(settings.embed_model)
    return _model.encode(
        texts, normalize_embeddings=True, show_progress_bar=False
    ).tolist()


def chunk(text: str) -> list[str]:
    size, overlap = settings.chunk_chars, settings.chunk_overlap
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 1 <= size:
            cur = f"{cur}\n{p}" if cur else p
        else:
            if cur:
                chunks.append(cur)
            while len(p) > size:  # very long paragraph
                chunks.append(p[:size])
                p = p[size - overlap:]
            cur = p
    if cur:
        chunks.append(cur)
    return chunks
