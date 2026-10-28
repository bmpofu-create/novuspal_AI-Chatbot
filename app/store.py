"""Vector memory. Chroma is the default; Postgres/pgvector is optional.

A vector store fits this chatbot because a question should retrieve the page
chunks closest in meaning. A document store would only match keywords, and a
graph is unnecessary without relationships such as major-to-advisor links.
The chosen database does not embed text; app/embed.py does that locally.
"""
from .config import settings

if settings.vector_backend == "pgvector":
    from .store_pg import prune_source, search, stats, upsert_doc  # noqa: F401
else:
    from .store_chroma import prune_source, search, stats, upsert_doc  # noqa: F401
