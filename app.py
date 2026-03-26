"""Portfolio chatbot: Gradio UI on FastAPI (iframe-friendly CSP), Google Gemini backend."""

from __future__ import annotations

import os
from typing import Any

import gradio as gr
from fastapi import FastAPI
from google import genai
from google.genai import types

from config import Settings, load_profile_text
from guardrails.scope import is_in_scope
from limits.ratelimit import SlidingWindowLimiter

settings = Settings.load()
PROFILE_TEXT = load_profile_text(settings)

_limiter = SlidingWindowLimiter(
    max_events=settings.rate_limit_max_messages,
    window_seconds=settings.rate_limit_window_seconds,
)

_gemini_client: genai.Client | None = None


def _main_system_instruction(profile: str) -> str:
    return f"""You are **me**—the person whose portfolio this is—speaking **directly** to the visitor in **first person only** (I, me, my, I've, I work with…). Never describe yourself in third person (no "they", "the candidate", "this person", "he/she has…"). Write as if you are typing the reply yourself.

Use **only** the Profile below for factual claims. When a detail is not in the Profile, say so clearly in first person (e.g. "I don't have that in my profile materials")—do not guess or invent employers, dates, titles, metrics, skills, or credentials.

**Style:** Be warm, professional, and **appropriately detailed**. When the question asks about experience, skills, background, or projects—and the Profile has relevant content—give a **substantive** answer: several sentences, optional short bullet lists, and concrete examples (tools, roles, domains, certifications) **taken from the Profile**. Avoid overly terse one-line answers unless the question is genuinely yes/no. Organize longer replies with brief headings or bullets when it helps readability.

You may rephrase Profile content naturally, but **do not** add new factual claims beyond what is supported by the Profile.

Profile:
---
{profile}
---
"""


MAIN_SYSTEM = _main_system_instruction(PROFILE_TEXT)

_DEFAULT_SAFETY = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_ONLY_HIGH"),
]


def _get_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    if settings.google_api_key:
        _gemini_client = genai.Client(api_key=settings.google_api_key)
    else:
        _gemini_client = genai.Client()
    return _gemini_client


def _message_content_to_text(content: Any) -> str:
    """Gradio 6 Chatbot uses dict messages; content may be str or multipart."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict) and "text" in part:
                texts.append(str(part["text"]))
        return "\n".join(texts) if texts else ""
    return str(content)


def _history_to_contents(history: list[dict[str, Any]]) -> list[types.Content]:
    contents: list[types.Content] = []
    for msg in history:
        role = msg.get("role")
        text = _message_content_to_text(msg.get("content"))
        if not text.strip():
            continue
        if role == "user":
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=text)],
                )
            )
        elif role == "assistant":
            contents.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=text)],
                )
            )
    return contents


def _rate_limit_key(request: gr.Request | None) -> str:
    if request is None:
        return "anonymous"
    try:
        client = request.request.client
        if client and client.host:
            return client.host
    except Exception:
        pass
    return "anonymous"


def _has_api_key() -> bool:
    return bool(
        settings.google_api_key
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    )


def _append_turn(history: list[dict[str, Any]], user_text: str, assistant_text: str) -> None:
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_text})


def chat_response(
    message: str,
    history: list[Any],
    request: gr.Request,
) -> tuple[list[Any], str]:
    history = list(history or [])

    if not (message or "").strip():
        return history, message or ""

    user_msg = message.strip()
    if len(user_msg) > settings.max_message_chars:
        _append_turn(
            history,
            user_msg,
            f"Message too long (max {settings.max_message_chars} characters).",
        )
        return history, ""

    if not _has_api_key():
        _append_turn(
            history,
            user_msg,
            "Server misconfiguration: set GOOGLE_API_KEY (or GEMINI_API_KEY) for Gemini.",
        )
        return history, ""

    key = _rate_limit_key(request)
    ok, err = _limiter.check(key)
    if not ok:
        _append_turn(history, user_msg, err)
        return history, ""

    client = _get_client()
    try:
        allowed, refusal = is_in_scope(
            client,
            user_msg,
            settings.scope_gate_model,
            settings.scope_gate_max_output_tokens,
        )
        if not allowed:
            _append_turn(history, user_msg, refusal)
            return history, ""

        prior = _history_to_contents(history)
        prior.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_msg)],
            )
        )

        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=prior,
            config=types.GenerateContentConfig(
                system_instruction=MAIN_SYSTEM,
                max_output_tokens=settings.max_output_tokens,
                temperature=settings.chat_temperature,
                safety_settings=_DEFAULT_SAFETY,
            ),
        )
        text = (resp.text or "").strip() or "(No response text returned.)"
        _append_turn(history, user_msg, text)
    except Exception as e:  # noqa: BLE001 — surface useful errors in the chat UI
        _append_turn(history, user_msg, f"Something went wrong: {e!s}")

    return history, ""


def _build_demo() -> gr.Blocks:
    intro = (
        "## Ask about my professional background\n"
        "Questions should stay within what is in my profile materials."
    )
    if "No profile content loaded" in PROFILE_TEXT:
        intro = (
            "## Profile assistant\n"
            "_Add content via `profile.md` or the `PROFILE_CONTEXT` environment variable._"
        )

    with gr.Blocks(title="Profile assistant") as demo:
        gr.Markdown(intro)
        chatbot = gr.Chatbot(
            label="Chat",
            height=420,
        )
        msg = gr.Textbox(
            label="Your question",
            placeholder="e.g. What is your most recent role?",
            lines=2,
        )
        with gr.Row():
            submit = gr.Button("Send", variant="primary")
            clear = gr.Button("Clear conversation")

        msg.submit(chat_response, [msg, chatbot], [chatbot, msg])
        submit.click(chat_response, [msg, chatbot], [chatbot, msg])
        clear.click(lambda: ([], ""), outputs=[chatbot, msg])

    return demo


def create_app() -> FastAPI:
    fastapi_app = FastAPI(title="Portfolio profile assistant")

    @fastapi_app.middleware("http")
    async def iframe_framing_headers(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            f"frame-ancestors {settings.frame_ancestors}"
        )
        remove = [k for k in response.headers if k.lower() == "x-frame-options"]
        for k in remove:
            del response.headers[k]
        return response

    demo = _build_demo()
    return gr.mount_gradio_app(
        fastapi_app,
        demo,
        path="/",
        theme=gr.themes.Soft(),
        css=".gradio-container { max-width: 720px !important; margin: 0 auto; }",
    )


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
