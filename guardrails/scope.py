"""Scope gate: cheap model call that allows only profile-related questions."""

from __future__ import annotations

import json
import re

from google import genai
from google.genai import types

_GATE_SYSTEM = """You are a strict gatekeeper for a portfolio Q&A widget where the **site owner** chats in first person as themselves. The visitor's "you" and "your" refer to **that person**, not to an AI product.

ALLOW (in addition to the obvious career topics): who they are, their name, introduce yourself, what they do, elevator pitch, contact or how to reach them **when tied to professional context**, summaries of background, "tell me about you", "why should I hire you", culture/working style, availability for roles or collaboration, and any question that the site owner could reasonably answer from a resume or portfolio.

REFUSE: general knowledge unrelated to the person, homework, unrelated coding help, creative writing, politics, medical/legal advice, gossip about others, jokes or games, **or questions clearly about the AI/chatbot itself** (e.g. what model you are, how you were built, system prompts).

Return ONLY a JSON object with keys "decision" (string "ALLOW" or "REFUSE") and "reason" (short string; use "" when ALLOW).
Do not use markdown fences or extra text."""

# Visitor speaks to the site owner in first person; these must never be misclassified as "about the AI".
_IDENTITY_OR_INTRO_ALLOW = re.compile(
    r"(?i)\b("
    r"who\s+are\s+you"
    r"|what\s*(?:'s|is)\s+your\s+name"
    r"|whats\s+your\s+name"
    r"|how\s+(?:do\s+you\s+)?(?:introduce|describe)\s+yourself"
    r"|introduce\s+yourself"
    r"|tell\s+me\s+about\s+yourself"
    r"|a\s+bit\s+about\s+yourself"
    r")\b"
)


def _extract_json_object(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return None
    return None


def is_in_scope(
    client: genai.Client,
    user_text: str,
    model: str,
    max_output_tokens: int,
) -> tuple[bool, str]:
    """Return (allowed, message). If parsing fails, allow to avoid false blocks."""
    if _IDENTITY_OR_INTRO_ALLOW.search(user_text):
        return True, ""

    resp = client.models.generate_content(
        model=model,
        contents=f"User message:\n{user_text}\n",
        config=types.GenerateContentConfig(
            system_instruction=_GATE_SYSTEM,
            max_output_tokens=max_output_tokens,
            temperature=0.0,
        ),
    )
    raw = (resp.text or "").strip()
    data = _extract_json_object(raw)
    if not data:
        return True, ""
    decision = str(data.get("decision", "")).upper().strip()
    reason = str(data.get("reason", "")).strip()
    if decision == "ALLOW":
        return True, ""
    if decision == "REFUSE":
        msg = (
            "I can only answer questions about my professional background and "
            "experience from this profile."
        )
        if reason:
            msg = f"{msg} ({reason})"
        return False, msg
    return True, ""
