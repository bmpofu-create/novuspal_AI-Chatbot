from dataclasses import dataclass, field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""  # unused; answers are generated on this machine
    llm_backend: str = "transformers"  # transformers | ollama
    llm_model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    ollama_base_url: str = "http://127.0.0.1:11434"
    max_new_tokens: int = 320
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chroma_dir: str = "./chroma_data"
    user_agent: str = "NovusPalBot/0.1"
    admin_api_key: str = "novuspal"
    request_delay_s: float = 1.0  # politeness delay between requests to the same host
    max_pages_per_source: int = 60
    chunk_chars: int = 1200
    chunk_overlap: int = 150
    vector_backend: str = "chroma"  # chroma | pgvector
    database_url: str = "postgresql://postgres:postgres@localhost:5432/novuspal"
    cors_origins: str = ""  # comma-separated; empty = same-origin only


settings = Settings()


@dataclass
class Source:
    """One thing to keep fresh in the vector DB.

    kind:
      - "feed": RSS/Atom/iCal-style feed (best for news and events: cheap, near real-time)
      - "page": a fixed list of pages
      - "crawl": start at `urls`, follow same-site links matching `link_patterns`
    """
    name: str
    category: str  # news | events | library | tutoring | registration | general
    kind: str
    urls: list[str]
    refresh_minutes: int
    link_patterns: list[str] = field(default_factory=list)
    render_js: bool = False  # True for JavaScript-rendered pages (needs Playwright)


# NOTE: verify every URL below (and prefer official feeds) before the first run.
# Only list PUBLIC pages. Anything behind MTU login (Banweb, Canvas, student records)
# must NOT be scraped; use an official API / IT-approved integration instead.
SOURCES: list[Source] = [
    Source("mtu-news", "news", "feed", ["https://www.mtu.edu/news/"], refresh_minutes=15),
    Source("mtu-events", "events", "page", ["https://www.mtu.edu/events/"], refresh_minutes=30),
    Source("library", "library", "crawl", ["https://www.mtu.edu/library/"], refresh_minutes=360,
           link_patterns=["/library/"]),
    Source("tutoring", "tutoring", "crawl", ["https://www.mtu.edu/learning-center/"], refresh_minutes=360,
           link_patterns=["/learning-center/"]),
    Source("registration", "registration", "crawl", ["https://www.mtu.edu/registrar/"], refresh_minutes=720,
           link_patterns=["/registrar/"]),
]
