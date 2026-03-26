"""Load settings from environment (and optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _comma_split_origins(raw: str) -> str:
    """Normalize comma-separated origins into CSP frame-ancestors token list."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return " ".join(parts) if parts else "*"


@dataclass(frozen=True)
class Settings:
    google_api_key: str | None
    gemini_model: str
    scope_gate_model: str
    profile_context: str
    profile_path: Path
    max_message_chars: int
    max_output_tokens: int
    chat_temperature: float
    scope_gate_max_output_tokens: int
    rate_limit_max_messages: int
    rate_limit_window_seconds: int
    frame_ancestors: str
    host: str
    port: int

    @classmethod
    def load(cls) -> Settings:
        key = (
            os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or ""
        ).strip()
        profile_env = (os.environ.get("PROFILE_CONTEXT") or "").strip()
        rel_profile = (os.environ.get("PROFILE_PATH") or "Profile.pdf").strip()
        frame_raw = (os.environ.get("FRAME_ANCESTORS") or "*").strip()

        return cls(
            google_api_key=key or None,
            gemini_model=(os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip(),
            scope_gate_model=(
                os.environ.get("SCOPE_GATE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
            ).strip(),
            profile_context=profile_env,
            profile_path=(ROOT / rel_profile).resolve(),
            max_message_chars=_int("MAX_MESSAGE_CHARS", 2000),
            max_output_tokens=_int("MAX_OUTPUT_TOKENS", 4096),
            chat_temperature=_float("CHAT_TEMPERATURE", 0.65),
            scope_gate_max_output_tokens=_int("SCOPE_GATE_MAX_OUTPUT_TOKENS", 128),
            rate_limit_max_messages=_int("RATE_LIMIT_MAX_MESSAGES", 20),
            rate_limit_window_seconds=_int("RATE_LIMIT_WINDOW_SECONDS", 900),
            frame_ancestors=_comma_split_origins(frame_raw),
            host=(os.environ.get("HOST") or "0.0.0.0").strip(),
            port=_int("PORT", 7860),
        )


def _extract_pdf_text(path: Path) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        parts: list[str] = []
        for page in doc:
            parts.append(page.get_text())
        return "\n".join(parts).strip()
    finally:
        doc.close()


def load_profile_text(settings: Settings) -> str:
    """PROFILE_CONTEXT env wins, else PROFILE_PATH file (.pdf, .md, .txt)."""
    if settings.profile_context:
        return settings.profile_context
    path = settings.profile_path
    if not path.is_file():
        return (
            "(No profile content loaded. Set PROFILE_CONTEXT or place a file at "
            f"{path.name}.)"
        )
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            text = _extract_pdf_text(path)
            if not text:
                return (
                    f"(Could not extract text from {path.name}. The PDF may be image-only; "
                    "try an exported text PDF or use PROFILE_CONTEXT.)"
                )
            return text
        return path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"(Error reading profile file {path.name}: {e})"
