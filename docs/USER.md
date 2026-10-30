# NovusPal user guide

NovusPal is a campus assistant for Michigan Technological University. You type a question, and it answers from public MTU pages that the app has already read: news, events, the library, tutoring, and registration.

It does not see your Banweb account, Canvas courses, grades, or personal schedule. If a fact is not on those public pages, NovusPal cannot look it up.

## Start the app

From the project folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave that window open. In a browser, open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Stop the server with Ctrl+C in that window.

The first time you ask a question, the app may download a small local model and read campus pages in the background. That wait is normal. Later questions in the same session start sooner. Answers still take longer than a typical website chatbot because the model runs on this computer.

If this is a brand-new copy of the project, create the environment once:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

No API key is required.

## Ask a question

1. Open the page. The welcome line is “Ask about hours, events, tutoring, or registration.”
2. Type in the box labeled “Ask about campus…”, or click one of the starter cards:
   - **Library hours** — when the library is open and where to study
   - **Tutoring** — what is offered and how to join
   - **What’s happening** — events to put on a calendar
   - **Registration** — steps, dates, and where to go
3. Press Enter or the send arrow. Shift+Enter adds a new line without sending.
4. Your question appears on the right. NovusPal’s reply appears on the left and fills in as it is written.
5. Page titles under the reply are the public pages the answer used. Click a title to open that page in a new tab.

You can keep talking in the same tab. NovusPal remembers the recent turns in that browser tab only. Refreshing the page clears the conversation. Nothing from the chat is saved on the server.

The box accepts up to 2000 characters. Wait until the current reply finishes before sending another. The send button stays off while a reply is being written.

The page follows your system light or dark theme.

## Narrow the topic

The buttons under the title limit which pages are searched:

| Button | What it searches |
|---|---|
| All | Every stored page |
| News | MTU news |
| Events | The events page |
| Library | Library pages |
| Tutoring | Learning-center pages |
| Registration | Registrar pages |

All is selected when you first open the page. Click another topic before you send if you want a narrower answer. If that topic has no matching pages, the app searches everything instead.

## What a good answer looks like

The reply should state the fact in the first sentence: hours, a place, a date, a name, or the steps to take. It should not tell you to “see the website” instead of answering.

Use the links under the message when you need the original page. Hours and dates on that page are the authority if the reply and the page disagree.

## What it can answer

Questions about public information the app has stored, for example:

- Library hours and study space described on the library site
- How registration works, as written on registrar pages
- News stories from the MTU news pages
- Tutoring or events, when those pages were collected successfully

## What it cannot answer

- Your class schedule, bill, holds, grades, or anything behind an MTU login
- A page that has not been collected yet, or a site the app does not read
- Facts it would have to invent. If the stored pages only partly cover the question, the reply should give what it has and say what it cannot confirm

Name the office, building, or date when an answer is vague. “Van Pelt library hours on Saturday” works better than “hours?”

## If something goes wrong

**The page does not load.** The server window must still be running, and the address must be [http://127.0.0.1:8000](http://127.0.0.1:8000).

**The first reply sits on the writing dots for a long time.** The model is loading, or campus pages are still being read. Leave the window open and wait. Check [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health). `chunks` should be greater than 0 before you expect a real answer. `llm_model` shows which local model is configured.

**“I don’t have campus pages loaded for that yet.”** The index is empty, or nothing matched. Wait for the first read to finish, then ask again. A topic button can also hide pages that live under a different topic; try All.

**“The local model could not answer.”** Ask again. If it keeps happening, the model files may not have downloaded. You need a network connection for that first download.

**“Ollama is not responding.”** The server is set to use Ollama (`LLM_BACKEND=ollama` in `.env`). Start Ollama, and pull the model named by `LLM_MODEL`, or switch `.env` back to `LLM_BACKEND=transformers` and restart the server.

**Tutoring or events answers stay empty.** The app starts from `https://www.mtu.edu/learning-center/` and `https://www.mtu.edu/events/`. If those addresses are not valid pages, nothing is stored for that topic. Library, news, and registrar pages can still work.

**An answer cuts off or sounds slightly wrong.** The reply is generated by a small model on this computer. Open the source link under the message and use the time, date, or policy written there.

**You changed the code and the page looks the same.** Stop the server and start it again. It does not reload code by itself. The chat page is sent with no-cache, so a refresh picks up a new `index.html` after a restart.

## Running it for other people

Bind the server only where you intend people to reach it. Anyone who can open the site can ask questions. They cannot trigger a new read of campus pages unless they have the admin key.

To refresh the stored pages yourself:

```powershell
curl -X POST http://127.0.0.1:8000/ingest -H "X-API-Key: YOUR_KEY"
```

Replace `YOUR_KEY` with `ADMIN_API_KEY` from `.env`. One source at a time:

```powershell
curl -X POST http://127.0.0.1:8000/ingest/library -H "X-API-Key: YOUR_KEY"
```

Source names are `mtu-news`, `mtu-events`, `library`, `tutoring`, and `registration`.

Keep `.env` on your machine. Do not publish it. How the pieces fit together is in [TECHNICAL.md](TECHNICAL.md).
