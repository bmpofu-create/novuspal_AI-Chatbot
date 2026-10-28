"""Local retrieval-augmented answering.

Memory is a vector store (Chroma, or Postgres/pgvector). A graph database is
not used: questions look up similar page text, not relationships between
records. Chroma and pgvector store vectors; they do not create them.
Embeddings are computed locally in app/embed.py.

LangChain builds the prompt and runs the model. The model itself is hosted
here: Hugging Face Transformers by default, or Ollama on localhost when
LLM_BACKEND=ollama. Retrieved campus text is not sent to an external API.
"""
import os
import threading
from collections.abc import Iterator

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from .config import settings
from . import store

SYSTEM = """You are NovusPal, a student assistant for Michigan Technological University.
Talk like a knowledgeable friend on campus: warm, specific, and complete.

Campus notes are included with the question. They are your only source of campus facts.
- Open with the answer itself, in the first sentence.
- Include the concrete details a student can use: dates, hours, places, names, phone numbers, and the steps to take.
- Write short paragraphs. Use a brief list only when the student needs steps or a few distinct options.
- If a fact is in the notes, state that fact in your own words. Copy clock times, dates, and numbers exactly as written in the notes. Never answer by pointing at a page, a link, a title, or a source number.
- Do not include citation markers like [1], URLs, or a sources list. The app shows sources separately.
- If the notes only partly cover the question, give every specific detail they do contain, then say in one sentence what you cannot confirm.
- Never invent dates, hours, prices, phone numbers, or policies.
- Do not quote the notes or describe them. Just answer."""

_NOTE_CHARS = 900
_chain = None
_load_lock = threading.Lock()
_gen_lock = threading.Lock()
_tokenizer = None
_model = None


def runtime_info() -> dict:
    return {"llm_backend": settings.llm_backend, "llm_model": settings.llm_model}


def _prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", SYSTEM),
        (
            "human",
            "{history}Campus notes:\n\n{context}\n\n"
            "Student question: {question}\n\n"
            "Answer the student directly. State the specific facts. "
            "Do not tell them to look up the notes.",
        ),
    ])


def _retrieve(message: str, k: int, category: str | None) -> list[dict]:
    hits = store.search(message, k=k, category=category)
    if not hits and category:
        hits = store.search(message, k=k, category=None)
    return hits


def _pack_notes(hits: list[dict]) -> list[dict]:
    notes: list[dict] = []
    by_url: dict[str, dict] = {}
    for hit in hits:
        text = (hit.get("text") or "").strip()
        url = hit.get("url") or ""
        if not text:
            continue
        existing = by_url.get(url)
        if existing:
            if text not in existing["text"] and len(existing["text"]) < _NOTE_CHARS:
                room = _NOTE_CHARS - len(existing["text"]) - 1
                existing["text"] = f"{existing['text']}\n{text[:room]}".strip()
            existing["score"] = max(existing["score"], hit.get("score") or 0)
            continue
        note = {
            "title": (hit.get("title") or url or "Campus page").strip(),
            "url": url,
            "text": text[:_NOTE_CHARS],
            "score": hit.get("score") or 0,
        }
        by_url[url] = note
        notes.append(note)
    return notes


def _history_text(history) -> str:
    if not history:
        return ""
    lines = []
    for turn in list(history)[-6:]:
        who = "Student" if turn.role == "user" else "NovusPal"
        lines.append(f"{who}: {turn.content[:700]}")
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


def _context(notes: list[dict]) -> str:
    return "\n\n".join(f"Note {i} — {n['title']}\n{n['text']}" for i, n in enumerate(notes, 1))


def _load_transformers():
    global _tokenizer, _model
    if _model is not None:
        return _tokenizer, _model
    with _load_lock:
        if _model is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            _tokenizer = AutoTokenizer.from_pretrained(settings.llm_model)
            _model = AutoModelForCausalLM.from_pretrained(
                settings.llm_model,
                dtype=torch.float32,
            )
            _model.eval()
            if _tokenizer.pad_token_id is None:
                _tokenizer.pad_token = _tokenizer.eos_token
    return _tokenizer, _model


def warm_model() -> None:
    try:
        if settings.llm_backend == "transformers":
            _load_transformers()
        else:
            _get_chain()
    except Exception:
        import logging
        logging.getLogger("novuspal").exception("local model warmup failed")


class _LocalChatModel(Runnable):
    """Instruct model loaded with Transformers. Generation stays on this machine."""

    def invoke(self, input, config=None, **kwargs) -> str:  # noqa: A002
        return "".join(self.stream(input, config, **kwargs))

    def stream(self, input, config=None, **kwargs) -> Iterator[str]:  # noqa: A002
        from transformers import TextIteratorStreamer

        tokenizer, model = _load_transformers()
        messages = []
        for message in input.to_messages():
            role = {"system": "system", "human": "user", "ai": "assistant"}.get(message.type, "user")
            messages.append({"role": role, "content": message.content})
        prompt_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        streamer = TextIteratorStreamer(
            tokenizer, skip_prompt=True, skip_special_tokens=True
        )
        encoded = tokenizer(prompt_text, return_tensors="pt")
        gen_kwargs = dict(
            **encoded,
            streamer=streamer,
            max_new_tokens=settings.max_new_tokens,
            do_sample=True,
            temperature=0.4,
            top_p=0.9,
            repetition_penalty=1.08,
            pad_token_id=tokenizer.pad_token_id,
        )

        def _run() -> None:
            import torch
            with torch.no_grad():
                model.generate(**gen_kwargs)

        threading.Thread(target=_run, daemon=True).start()
        for piece in streamer:
            if piece:
                yield piece


def _build_chain():
    prompt = _prompt()
    if settings.llm_backend == "ollama":
        from langchain_ollama import ChatOllama

        llm = ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=0.4,
            num_predict=settings.max_new_tokens,
        )
        return prompt | llm | StrOutputParser()
    if settings.llm_backend != "transformers":
        raise RuntimeError(
            f"Unknown LLM_BACKEND {settings.llm_backend!r}. Use transformers or ollama."
        )
    return prompt | _LocalChatModel() | StrOutputParser()


def _get_chain():
    global _chain
    if _chain is None:
        with _load_lock:
            if _chain is None:
                _chain = _build_chain()
    return _chain


def stream_chat(message: str, category: str | None, top_k: int, history) -> Iterator[dict]:
    yield {"type": "status"}
    notes = _pack_notes(_retrieve(message, top_k, category))
    if not notes:
        yield {
            "type": "token",
            "text": (
                "I don't have campus pages loaded for that yet. "
                "Ask again in a moment, or try another topic."
            ),
        }
        yield {"type": "done"}
        return

    inputs = {
        "history": _history_text(history),
        "context": _context(notes),
        "question": message,
    }
    sources = [
        {"n": i + 1, "title": n["title"], "url": n["url"]}
        for i, n in enumerate(notes)
        if n["url"]
    ]
    emitted = False
    try:
        with _gen_lock:
            for piece in _get_chain().stream(inputs):
                text = piece if isinstance(piece, str) else getattr(piece, "content", "") or ""
                if not text:
                    continue
                emitted = True
                yield {"type": "token", "text": text}
    except Exception as exc:
        import logging
        logging.getLogger("novuspal").exception("local model failed")
        if emitted:
            yield {"type": "sources", "sources": sources}
            yield {"type": "done"}
            return
        detail = "The local model could not answer."
        if settings.llm_backend == "ollama":
            detail = "Ollama is not responding. Start it and pull the model named in LLM_MODEL."
        elif "offline" in str(exc).lower() or "connect" in str(exc).lower():
            detail = "The local model could not be downloaded. Check the network and try again."
        yield {"type": "error", "text": detail}
        return

    if not emitted:
        yield {
            "type": "token",
            "text": (
                "I couldn't find a clear answer in the campus notes. "
                "Try naming the office, building, or date you care about."
            ),
        }
    yield {"type": "sources", "sources": sources}
    yield {"type": "done"}
