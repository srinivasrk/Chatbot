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

# Split by `prefers-color-scheme` so the iframe follows system light/dark. Gradio maps the same
# preference to its `*_dark` theme tokens; custom bubble/input rules apply only in light mode.
_EMBED_CSS = """
.gradio-container {
    max-width: 100% !important;
    margin: 0 auto !important;
    padding: 0.6rem 0.85rem 1rem !important;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}
#portfolio-chat-intro {
    margin-bottom: 0.45rem;
}
#portfolio-chat-intro h3 {
    font-weight: 650;
    letter-spacing: -0.02em;
    margin: 0 0 0.35rem 0;
    line-height: 1.25;
    font-size: 1.15rem;
}
#portfolio-chat-intro p {
    margin: 0;
    line-height: 1.55;
    font-size: 1rem;
}
.gradio-container .message-wrap .bot .prose,
.gradio-container .message-wrap .bot .prose.chatbot.md,
.gradio-container .message-wrap .user .prose,
.gradio-container .message-wrap .user .prose.chatbot.md {
    opacity: 1 !important;
}

@media (prefers-color-scheme: light) {
    .gradio-container .bubble-wrap {
        background: rgba(255, 255, 255, 0.55) !important;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        border-radius: 14px !important;
        border: 1px solid rgba(15, 118, 110, 0.14) !important;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
    }
    #portfolio-chat-intro h3 {
        color: #0f172a;
    }
    #portfolio-chat-intro p {
        color: #334155;
    }
    .gradio-container .message-wrap .bot {
        background-color: #ffffff !important;
        border-color: rgba(15, 23, 42, 0.12) !important;
        box-shadow: none !important;
        color: #0f172a !important;
    }
    .gradio-container .message-wrap .bot .prose,
    .gradio-container .message-wrap .bot .prose.chatbot.md {
        color: #0f172a !important;
    }
    .gradio-container .message-wrap .bot .prose a {
        color: #0f766e !important;
    }
    .gradio-container .message-wrap .bot .prose code {
        background: #f1f5f9 !important;
        color: #0f172a !important;
    }
    .gradio-container .message-wrap .bot .prose pre {
        background: #f1f5f9 !important;
        color: #0f172a !important;
    }
    .gradio-container .message-wrap .user {
        background: linear-gradient(180deg, #d1fae5 0%, #a7f3d0 100%) !important;
        box-shadow: none !important;
        border-color: rgba(13, 148, 136, 0.35) !important;
        color: #0f172a !important;
    }
    .gradio-container .message-wrap .user .prose,
    .gradio-container .message-wrap .user .prose.chatbot.md {
        color: #0f172a !important;
    }
    .gradio-container .bubble-wrap .placeholder,
    .gradio-container [data-testid="chatbot"] .placeholder {
        color: #64748b !important;
        opacity: 1 !important;
    }
    .gradio-container textarea,
    .gradio-container input[type="text"] {
        background: #ffffff !important;
        color: #0f172a !important;
    }
    .gradio-container textarea::placeholder {
        color: #64748b !important;
        opacity: 1 !important;
    }
}

@media (prefers-color-scheme: dark) {
    .gradio-container .bubble-wrap {
        background: rgba(15, 23, 42, 0.45) !important;
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-radius: 14px !important;
        border: 1px solid rgba(94, 234, 212, 0.14) !important;
    }
    #portfolio-chat-intro h3 {
        color: #f1f5f9;
    }
    #portfolio-chat-intro p {
        color: #cbd5e1;
    }
    .gradio-container .bubble-wrap .placeholder,
    .gradio-container [data-testid="chatbot"] .placeholder {
        color: #94a3b8 !important;
        opacity: 1 !important;
    }
}
"""


def _portfolio_theme() -> gr.themes.Soft:
    _page_light = "linear-gradient(165deg, #f4f6fa 0%, #eef1f8 48%, #ebf5f4 100%)"
    _page_dark = "linear-gradient(165deg, #0f172a 0%, #1e293b 52%, #134e4a 100%)"
    _block_light = "rgba(255, 255, 255, 0.78)"
    _block_dark = "rgba(30, 41, 59, 0.72)"
    _teal_border = "rgba(15, 118, 110, 0.11)"
    _teal_border_dark = "rgba(45, 212, 191, 0.2)"
    _field_light = "rgba(15, 23, 42, 0.1)"
    _field_dark = "rgba(148, 163, 184, 0.28)"
    return gr.themes.Soft(primary_hue="teal", neutral_hue="slate").set(
        body_background_fill=_page_light,
        body_background_fill_dark=_page_dark,
        block_background_fill=_block_light,
        block_background_fill_dark=_block_dark,
        block_border_color=_teal_border,
        block_border_color_dark=_teal_border_dark,
        border_color_primary=_field_light,
        border_color_primary_dark=_field_dark,
        border_color_accent="rgba(13, 148, 136, 0.35)",
        border_color_accent_dark="rgba(45, 212, 191, 0.4)",
        color_accent_soft="#ccfbf1",
        color_accent_soft_dark="rgba(45, 212, 191, 0.18)",
        block_border_width="1px",
        input_background_fill="#ffffff",
        input_background_fill_dark="#1e293b",
        input_border_color=_field_light,
        input_border_color_dark=_field_dark,
        input_placeholder_color="#64748b",
        input_placeholder_color_dark="#94a3b8",
    )


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
        "### Hi — thanks for stopping by\n\n"
        "Ask me about my work, projects, or background. "
        "I stick to what’s in my profile here so answers stay accurate and grounded in what I’ve shared."
    )
    if "No profile content loaded" in PROFILE_TEXT:
        intro = (
            "### Profile assistant\n\n"
            "_Add content via `profile.md` or the `PROFILE_CONTEXT` environment variable._"
        )

    with gr.Blocks(title="Portfolio chat") as demo:
        gr.Markdown(intro, elem_id="portfolio-chat-intro")
        chatbot = gr.Chatbot(
            height=420,
            show_label=False,
            placeholder=(
                "_Nothing here yet — type a question below and I’ll reply "
                "from my profile._"
            ),
        )
        msg = gr.Textbox(
            label="Message",
            placeholder="e.g. What are you focused on lately?",
            lines=2,
            show_label=False,
        )
        with gr.Row():
            submit = gr.Button("Send", variant="primary")
            clear = gr.Button("Clear chat")

        msg.submit(chat_response, [msg, chatbot], [chatbot, msg])
        submit.click(chat_response, [msg, chatbot], [chatbot, msg])
        clear.click(lambda: ([], ""), outputs=[chatbot, msg])

    return demo


# HF embeds *.hf.space inside huggingface.co; those parents must be allowed or the Space "App" tab breaks.
_HF_PARENT_ORIGINS = "https://huggingface.co https://www.huggingface.co"


def _frame_ancestors_header_value() -> str:
    """FRAME_ANCESTORS from env plus Hugging Face hub (unless user set *)."""
    fa = settings.frame_ancestors.strip()
    if fa == "*":
        return "*"
    return f"{fa} {_HF_PARENT_ORIGINS}"


def create_app() -> FastAPI:
    fastapi_app = FastAPI(title="Portfolio profile assistant")

    @fastapi_app.middleware("http")
    async def iframe_framing_headers(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            f"frame-ancestors {_frame_ancestors_header_value()}"
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
        theme=_portfolio_theme(),
        css=_EMBED_CSS,
        footer_links=[],
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
