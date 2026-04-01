"""Load settings from environment (and optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent

# Auto-synced from the portfolio repo when present; merged in `load_profile_text`.
AUTO_PROFILE_MD = ROOT / "profile.md"


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
    extra_profile_paths: tuple[Path, ...]
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
        extra_raw = (os.environ.get("EXTRA_PROFILE_PATHS") or "").strip()
        extra_paths: list[Path] = []
        for part in extra_raw.split(","):
            p = part.strip()
            if p:
                extra_paths.append((ROOT / p).resolve())
        frame_raw = (os.environ.get("FRAME_ANCESTORS") or "*").strip()

        return cls(
            google_api_key=key or None,
            gemini_model=(os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip(),
            scope_gate_model=(
                os.environ.get("SCOPE_GATE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
            ).strip(),
            profile_context=profile_env,
            profile_path=(ROOT / rel_profile).resolve(),
            extra_profile_paths=tuple(extra_paths),
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


def _read_profile_file(path: Path) -> str:
    """Read one .pdf / .md / .txt profile fragment; path must exist."""
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


def load_profile_text(settings: Settings) -> str:
    """Primary: PROFILE_CONTEXT else PROFILE_PATH; then EXTRA_PROFILE_PATHS; then profile.md if present."""
    parts: list[str] = []
    seen_resolved: set[Path] = set()

    if settings.profile_context:
        parts.append(settings.profile_context)
    else:
        path = settings.profile_path
        if not path.is_file():
            parts.append(
                "(No primary profile file. Set PROFILE_CONTEXT or place a file at "
                f"{path.name}.)"
            )
        else:
            parts.append(_read_profile_file(path))
            seen_resolved.add(path.resolve())

    for extra in settings.extra_profile_paths:
        if not extra.is_file():
            continue
        r = extra.resolve()
        if r in seen_resolved:
            continue
        seen_resolved.add(r)
        parts.append(
            f"\n\n---\n\n### More from my public site ({extra.name})\n\n{_read_profile_file(extra)}"
        )

    auto_md = AUTO_PROFILE_MD
    if auto_md.is_file():
        md_resolved = auto_md.resolve()
        if md_resolved not in seen_resolved:
            parts.append(
                "\n\n---\n\n### Live portfolio export (profile.md)\n\n"
                f"{_read_profile_file(auto_md)}"
            )

    return "".join(parts).strip()
