"""Polite fetching + clean text extraction."""
import re
import time
import hashlib
import logging
import threading
from dataclasses import dataclass
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

from .config import Source, settings

log = logging.getLogger("scraper")

_robots: dict[str, RobotFileParser] = {}
_last_hit: dict[str, float] = {}


@dataclass
class Doc:
    url: str
    title: str
    text: str
    category: str
    source: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def _allowed(client: httpx.Client, url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(base)
    if rp is None:
        rp = RobotFileParser()
        try:
            r = client.get(f"{base}/robots.txt", timeout=10)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except httpx.HTTPError:
            rp.parse([])
        _robots[base] = rp
    return rp.can_fetch(settings.user_agent, url)


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    if not _allowed(client, url):
        log.info("robots.txt disallows %s", url)
        return None
    host = urlparse(url).netloc
    wait = settings.request_delay_s - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    rend = getattr(_ctx, "renderer", None)
    if rend is not None:
        return rend.get(url)
    try:
        r = client.get(url, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return r
    except httpx.HTTPError as e:
        log.warning("fetch failed %s: %s", url, e)
        return None


def _extract(html: str, url: str) -> tuple[str, str]:
    text = trafilatura.extract(html, url=url, include_tables=True, include_links=False) or ""
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string or "").strip() if soup.title else url
    if len(text) < 200:  # trafilatura found too little; fall back to visible text
        for t in soup(["script", "style", "nav", "footer", "header"]):
            t.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return title, text.strip()


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": settings.user_agent})


_ctx = threading.local()


class _Rendered:
    """Minimal stand-in for httpx.Response for browser-rendered pages."""
    def __init__(self, text: str):
        self.text = text
        self.headers = {"content-type": "text/html"}


class _Renderer:
    """Headless Chromium via Playwright, one browser per fetch_source call (same thread)."""
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page(user_agent=settings.user_agent)
        return self

    def get(self, url: str):
        try:
            self._page.goto(url, wait_until="networkidle", timeout=30000)
            return _Rendered(self._page.content())
        except Exception as e:  # playwright raises its own error types
            log.warning("render failed %s: %s", url, e)
            return None

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()


def fetch_source(src: Source) -> list[Doc]:
    if src.render_js and src.kind != "feed":
        try:
            with _Renderer() as rend:
                _ctx.renderer = rend
                try:
                    return _fetch(src)
                finally:
                    _ctx.renderer = None
        except ImportError:
            log.warning("render_js set for %s but Playwright is not installed; "
                        "run: pip install playwright && playwright install chromium", src.name)
    return _fetch(src)


def _fetch(src: Source) -> list[Doc]:
    docs: list[Doc] = []
    with _client() as client:
        if src.kind == "feed":
            docs += _from_feeds(client, src)
        elif src.kind == "page":
            for u in src.urls:
                d = _page(client, src, u)
                if d:
                    docs.append(d)
        elif src.kind == "crawl":
            docs += _crawl(client, src)
    return docs


def _page(client: httpx.Client, src: Source, url: str) -> Doc | None:
    r = _get(client, url)
    if not r or "html" not in r.headers.get("content-type", ""):
        return None
    title, text = _extract(r.text, url)
    return Doc(url, title, text, src.category, src.name) if text else None


def _from_feeds(client: httpx.Client, src: Source) -> list[Doc]:
    docs: list[Doc] = []
    for u in src.urls:
        r = _get(client, u)
        if not r:
            continue
        ctype = r.headers.get("content-type", "")
        if "xml" in ctype or "rss" in ctype or "atom" in ctype:
            feed = feedparser.parse(r.text)
            for e in feed.entries[:50]:
                link = e.get("link")
                if link:
                    d = _page(client, src, link)
                    if d:
                        docs.append(d)
        else:
            # Landing page, not a feed: discover article links on it.
            soup = BeautifulSoup(r.text, "lxml")
            alt = soup.find("link", attrs={"type": re.compile("rss|atom")})
            if alt and alt.get("href"):
                docs += _from_feeds(client, Source(src.name, src.category, "feed",
                                                  [urljoin(u, alt["href"])], src.refresh_minutes))
            else:
                docs += _crawl(client, Source(src.name, src.category, "crawl", [u],
                                              src.refresh_minutes, link_patterns=[urlparse(u).path]))
    return docs


def _crawl(client: httpx.Client, src: Source) -> list[Doc]:
    seen: set[str] = set()
    queue = list(src.urls)
    docs: list[Doc] = []
    hosts = {urlparse(u).netloc for u in src.urls}
    while queue and len(seen) < settings.max_pages_per_source:
        url = urldefrag(queue.pop(0))[0]
        if url in seen:
            continue
        seen.add(url)
        r = _get(client, url)
        if not r or "html" not in r.headers.get("content-type", ""):
            continue
        title, text = _extract(r.text, url)
        if text:
            docs.append(Doc(url, title, text, src.category, src.name))
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            nxt = urldefrag(urljoin(url, a["href"]))[0]
            p = urlparse(nxt)
            if p.netloc in hosts and nxt not in seen and \
               (not src.link_patterns or any(pat in p.path for pat in src.link_patterns)) and \
               not re.search(r"\.(pdf|jpg|png|zip|docx?|xlsx?)$", p.path, re.I):
                queue.append(nxt)
    return docs
