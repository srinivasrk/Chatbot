"""Scope gate: cheap model call that allows only profile-related questions."""

from __future__ import annotations

import json
import re

from google import genai
from google.genai import types

_GATE_SYSTEM = """You are a strict gatekeeper for a portfolio Q&A assistant.
ALLOW only questions about the site owner's professional profile: employment history, skills, education, certifications, projects, tech stack, how they work, hiring or collaboration intent related to their career.
REFUSE: general knowledge unrelated to the person, homework, unrelated coding help, creative writing, politics, medical/legal advice, the assistant's own opinions on world events, personal life gossip about strangers, jokes or games, or anything not clearly about the person described in the profile materials.

Return ONLY a JSON object with keys "decision" (string "ALLOW" or "REFUSE") and "reason" (short string; use "" when ALLOW).
Do not use markdown fences or extra text."""


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
