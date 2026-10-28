# NovusPal

Student chat for Michigan Technological University. A FastAPI app reads public MTU pages into a local vector database and answers questions with a model that runs on this machine. Replies stream into the chat page as they are written. The answer states the facts directly; matching campus pages are shown separately under the message.

Answers do not call Gemini, OpenAI, or any other hosted model API. The retrieved page text stays local.

## Run

The virtual environment is already in `.venv`. From this folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave that window open, then open http://127.0.0.1:8000. Stop the server with Ctrl+C.

On macOS or Linux, from an activated virtual environment:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API docs are at http://127.0.0.1:8000/docs.

### First-time setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

No API key is required. `.env` selects the local model:

- `LLM_BACKEND=transformers` downloads and runs `LLM_MODEL` (default `Qwen/Qwen2.5-0.5B-Instruct`) with Hugging Face Transformers. The first question waits while those weights download.
- `LLM_BACKEND=ollama` sends the prompt to Ollama at `OLLAMA_BASE_URL` on this computer. Install Ollama, run `ollama pull` for the name in `LLM_MODEL`, and set that name to an Ollama tag such as `qwen2.5:0.5b`.

The first launch also loads the embedding model and starts reading the public pages in the background. Questions work once those pages are stored. `GET /health` shows how many chunks are loaded and which local model is configured.

## How the pieces fit

1. **Memory.** Chroma, a vector database, is the fit. Questions retrieve page chunks that mean the same thing. A keyword document store would miss paraphrases, and a graph database is not used because the app does not follow relationships between records. Postgres with pgvector is an optional replacement for Chroma when more than one server needs the same memory.
2. **Embeddings.** Search needs vectors. Chroma and pgvector do not create them. `app/embed.py` runs `sentence-transformers/all-MiniLM-L6-v2` locally for both stored pages and questions.
3. **LangChain.** `app/rag.py` uses LangChain to assemble the prompt and call the local model. Scraping, chunking, and the vector store stay in this project because the pages and metadata are already stored that way.
4. **Local model.** Generation uses Transformers or Ollama. Campus notes are not sent to a hosted chat API.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | chunk count and last ingest result per source |
| GET | `/sources` | configured sources |
| GET | `/search?q=...&category=library` | raw vector search |
| POST | `/chat` | streamed answer for `{ "message": "...", "category": null, "history": [] }` |
| POST | `/ingest`, `/ingest/{source}` | force a refresh (header `X-API-Key`) |

`/chat` responds with server-sent events: `token` text as it is written, then `sources` (title and URL), then `done`. An `error` event means the model was busy or timed out; ask again.

`category` limits retrieval to `news`, `events`, `library`, `tutoring`, or `registration`. Leave it null to search everything. `history` is optional prior turns, up to eight, each `{ "role": "user" | "assistant", "content": "..." }`.

## How fresh the pages stay

Scraping is polling, not push. Each source has a `refresh_minutes` interval (news 15 min, events 30 min, library and tutoring 6 h, registrar 12 h). A page is re-embedded only when its content hash changes, and pages removed upstream are pruned. For true push, add an official RSS, iCal, or webhook as a `feed` source.

## Before you scrape

1. Verify the URLs in `app/config.py` and prefer official feeds.
2. Public pages only. Student records behind MTU login (Banweb, Canvas, personal schedules) must not be scraped. That is FERPA-protected. Use public registrar pages, or an IT-approved API for personal data.
3. The scraper obeys `robots.txt`, waits between requests to the same host, and identifies itself with `USER_AGENT`. Tell MTU IT or Web Services you are running it.
4. For a JavaScript-rendered page, set `render_js=True` on that source in `app/config.py`, then `pip install -r requirements-optional.txt` and `playwright install chromium`. Without Playwright the scraper falls back to a plain fetch.

## Production notes

- Use one worker. The scheduler runs inside the app process. For more than one web process, move ingestion to its own worker or cron job.
- Chroma is the default and needs no extra services. For more than one server, install `requirements-optional.txt`, run `docker compose up -d db`, and set `VECTOR_BACKEND=pgvector`. The table and index are created on startup. Switching backends does not copy existing chunks; call `POST /ingest` to refill.
- Add rate limiting and set `CORS_ORIGINS` before students reach `/chat` from another site.
