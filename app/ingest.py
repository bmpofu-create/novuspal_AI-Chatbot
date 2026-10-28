"""Ingestion pipeline + scheduler (near-real-time via polling and change detection)."""
import logging
import threading
from collections import Counter

from apscheduler.schedulers.background import BackgroundScheduler

from .config import SOURCES, Source
from .scraper import fetch_source
from . import store

log = logging.getLogger("ingest")
_lock = threading.Lock()
last_runs: dict[str, dict] = {}


def run_source(src: Source) -> dict:
    with _lock:  # one ingest at a time keeps the embedder/DB simple and the crawl polite
        docs = fetch_source(src)
        counts = Counter(store.upsert_doc(d) for d in docs)
        pruned = store.prune_source(src.name, {d.url for d in docs}) if docs else 0
        result = {"pages": len(docs), **counts, "pruned": pruned}
        last_runs[src.name] = result
        log.info("%s -> %s", src.name, result)
        return result


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="America/Detroit")
    for s in SOURCES:
        sched.add_job(run_source, "interval", args=[s], minutes=s.refresh_minutes,
                      id=s.name, max_instances=1, coalesce=True, next_run_time=None)
    sched.start()
    # Initial load in the background so startup is not blocked.
    for s in SOURCES:
        threading.Thread(target=run_source, args=(s,), daemon=True).start()
    return sched
