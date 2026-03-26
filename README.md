# Portfolio profile chatbot

A small **Gradio** chat UI served behind **FastAPI** (Uvicorn), backed by **Google Gemini**. Visitors ask questions about your professional background; answers are grounded in a **profile** you supply (PDF, Markdown, or plain text) and restricted by a **scope gate** plus **rate limiting** so the app is not a general-purpose chatbot or an open token sink.

The assistant is instructed to reply in **first person** (as you), with enough detail for portfolio use, only using facts present in your profile materials.

## Requirements

- **Python 3.11+**
- [**uv**](https://docs.astral.sh/uv/) for installs and runs (recommended)
- A [**Gemini API key**](https://aistudio.google.com/apikey) (`GOOGLE_API_KEY` or `GEMINI_API_KEY`)

## Quick start

1. **Clone or copy this project** and open a terminal in the project root.

2. **Install dependencies**

   ```bash
   uv sync
   ```

3. **Configure environment**

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set at least:

   - `GOOGLE_API_KEY=` *your key* (or use `GEMINI_API_KEY`)

   Optional: adjust models, limits, and paths (see [Configuration](#configuration)).

4. **Add your profile**

   - Default: put a **`Profile.pdf`** (text-selectable PDF works best) in the project root, **or**
   - Set `PROFILE_PATH` to another `.pdf`, `.md`, or `.txt`, **or**
   - Set `PROFILE_CONTEXT` to paste profile text directly (overrides the file).

   Restart the app after changing profile files so the system instruction reloads.

5. **Run the server**

   ```bash
   uv run uvicorn app:app --host 0.0.0.0 --port 7860
   ```

   Or:

   ```bash
   uv run python app.py
   ```

6. Open **http://127.0.0.1:7860** in a browser.

## Configuration

All settings are read from the environment (and optional `.env` via `python-dotenv`). Copy [.env.example](.env.example) to `.env` and edit.

| Variable | Purpose |
| -------- | ------- |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Gemini Developer API authentication (`GOOGLE_API_KEY` wins if both are set). |
| `GEMINI_MODEL` | Main chat model (default `gemini-2.5-flash`). |
| `SCOPE_GATE_MODEL` | Model for allow/refuse classification (defaults to `GEMINI_MODEL`). |
| `PROFILE_PATH` | Path to profile file relative to project root (default `Profile.pdf`). |
| `PROFILE_CONTEXT` | If non-empty, used as profile text instead of the file. |
| `MAX_MESSAGE_CHARS` | Max length of user input before rejection. |
| `MAX_OUTPUT_TOKENS` | Cap on model output length per reply. |
| `CHAT_TEMPERATURE` | Main reply temperature (default `0.65`). |
| `SCOPE_GATE_MAX_OUTPUT_TOKENS` | Cap for scope-gate JSON output. |
| `RATE_LIMIT_MAX_MESSAGES` | Max messages per IP per window. |
| `RATE_LIMIT_WINDOW_SECONDS` | Sliding window length in seconds. |
| `FRAME_ANCESTORS` | CSP `frame-ancestors` sources (comma-separated), or `*` for any parent. |
| `HOST` / `PORT` | Bind address and port when using `python app.py` (Uvicorn). |

For current model IDs and pricing, see the [Gemini API docs](https://ai.google.dev/gemini-api/docs/models) and [pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Embedding in your portfolio (iframe)

The app sets **`Content-Security-Policy: frame-ancestors …`** and strips **`X-Frame-Options`** when present so most portfolio sites can embed it.

1. Deploy the app over **HTTPS** and note its public URL (e.g. `https://chat.yourdomain.com/`).

2. Set **`FRAME_ANCESTORS`** in production to your site origins, for example:

   ```env
   FRAME_ANCESTORS=https://yourdomain.com,https://www.yourdomain.com
   ```

   Use `*` only if you are comfortable allowing any parent site to frame your chat.

3. On your portfolio page:

   ```html
   <iframe
     src="https://your-chat-host.example/"
     title="Profile assistant"
     loading="lazy"
     style="width:100%;min-height:640px;border:0;border-radius:8px"
   ></iframe>
   ```

If the iframe stays blank, check the browser **Network** / **Console** tabs for CSP or mixed-content errors.

## Project layout

| Path | Role |
| ---- | ---- |
| [app.py](app.py) | Gradio UI, Gemini calls, FastAPI app + iframe headers |
| [config.py](config.py) | Settings and profile loading (PDF via PyMuPDF, MD/TXT) |
| [guardrails/scope.py](guardrails/scope.py) | Scope gate: profile-related questions only |
| [limits/ratelimit.py](limits/ratelimit.py) | Sliding-window rate limiter |
| [pyproject.toml](pyproject.toml) | Dependencies managed by **uv** |
| `uv.lock` | Locked versions (commit this for reproducible deploys) |
| `.env.example` | Example environment variables |

## Behavior notes

- **Two Gemini calls per allowed message:** a short scope check, then the main reply. Off-topic questions are refused without running the main generation.
- **Profile text** is injected into the system instruction at import time, so **restart** after changing `Profile.pdf` or `PROFILE_CONTEXT`.
- **Scanned PDFs** (image-only) may extract little or no text; use a text-based export or `PROFILE_CONTEXT` / Markdown instead.
- **Secrets:** never commit `.env` or API keys. Consider keeping `Profile.pdf` out of public repos if it contains PII.

