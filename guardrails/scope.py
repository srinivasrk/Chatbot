"""Scope gate: cheap model call that allows only profile-related questions."""

from __future__ import annotations

import json
import re

from google import genai
from google.genai import types

_GATE_SYSTEM = """You are a strict gatekeeper for a portfolio Q&A widget where the **site owner** chats in first person as themselves. The visitor's "you" and "your" refer to **that person**, not to an AI product.

ALLOW (in addition to the obvious career topics): who they are, their name, introduce yourself, what they do, elevator pitch, contact or how to reach them **when tied to professional context**, summaries of background, "tell me about you", "why should I hire you", culture/working style, availability for roles or collaboration, **content from their public portfolio or personal website** (projects, skills lists, reading lists, site structure, "what's on your site"), and any question that the site owner could reasonably answer from a resume, portfolio, or that site.

**Reading / books (important):** ALLOW questions about **their** reading habits, **their** books section, what's **on their list** or profile, titles or authors **they** have shared, whether they enjoy reading, browsing or recommending **from what they've published** about themselves. Do **not** treat these as off-topic entertainment.

**Projects (important):** ALLOW questions about **their** projects, side projects, portfolio work, repos/links **they** listed, tech stacks, architecture, what each project does, comparisons between **their** projects, how **they** built something **they** shipped, demos, and **any project named or described** on their site or profile (including profile.md). Do **not** REFUSE as "coding help" when the visitor is clearly asking what **the site owner** built or maintains.

REFUSE: general knowledge unrelated to the person, homework, **unrelated** coding help (fix my bug, write my homework—not questions about the owner's own projects), creative writing, politics, medical/legal advice, gossip about others, jokes or games, **or questions clearly about the AI/chatbot itself** (e.g. what model you are, how you were built, system prompts).

**Book content (REFUSE):** questions that ask for **plot**, **spoilers**, **summary**, **synopsis**, **characters**, **themes**, **analysis**, reviews, "what is X about", "explain the ending", trivia, or other **intrinsic details of a book** that go beyond what appears on the site owner's shared list or profile. Those belong in ALLOW only if the user is clearly asking what **they personally said** in their materials about that book—and then only name facts, not encyclopedic detail. If the user wants general book info, REFUSE with reason exactly `BOOK_DETAIL`.

Return ONLY a JSON object with keys "decision" (string "ALLOW" or "REFUSE") and "reason" (short string; use "" when ALLOW; use exactly `BOOK_DETAIL` when refusing for book plot/summary/general content as above).
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

# Reading-list / "your books" questions; tight patterns so "what books teach X" still hits the gate.
_BOOKS_LIST_OR_EXPERIENCE_ALLOW = re.compile(
    r"(?i)("
    r"\bwhat\s+books\s+do\s+you\b"
    r"|\bwhat\s+books\s+are\s+(?:you|on\s+your)\b"
    r"|\bwhat\s+(?:are\s+you|do\s+you)\s+reading\b"
    r"|\bwhat\s+do\s+you\s+read\b"
    r"|\breading\s+list\b"
    r"|\byour\s+books\b"
    r"|\bbooks\s+on\s+(?:your\s+)?(?:site|portfolio|profile|page)\b"
    r"|\bdo\s+you\s+read\b"
    r"|\b(?:enjoy|like)\s+reading\b"
    r"|\b(?:favorite|favourite)\s+books?\b"
    r")"
)

# Portfolio / side-project questions; avoid bare "your projects" (matches inside "not your projects").
_PROJECTS_OR_PORTFOLIO_ALLOW = re.compile(
    r"(?i)("
    r"\bwhat\s+projects\s+(?:have\s+you|did\s+you|do\s+you|are\s+you)\b"
    r"|\bwhat\s+projects?\s+are\s+(?:on\s+your\s+)?(?:site|portfolio|profile|page)\b"
    r"|\b(?:tell\s+me\s+about|describe|explain)\s+your\s+projects?\b"
    r"|\b(?:side|portfolio)\s+projects?\b"
    r"|\bprojects?\s+on\s+(?:your\s+)?(?:site|portfolio|profile|page)\b"
    r"|\b(?:show|list)\s+(?:me\s+)?(?:your\s+)?projects?\b"
    r")"
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
    if _BOOKS_LIST_OR_EXPERIENCE_ALLOW.search(user_text):
        return True, ""
    if _PROJECTS_OR_PORTFOLIO_ALLOW.search(user_text):
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
        r = reason.upper().strip().strip("\"'").rstrip(".")
        if r == "BOOK_DETAIL" or r.startswith("BOOK_DETAIL"):
            msg = (
                "I'm happy to share what's on my reading list from my profile—but I don't "
                "go into plots, summaries, or other book details here."
            )
        else:
            msg = (
                "I can only answer questions about my professional background, projects, "
                "and experience from this profile."
            )
            if reason:
                msg = f"{msg} ({reason})"
        return False, msg
    return True, ""
