"""M1 — environment-driven config.

Role: load `.env`, expose resolved, path-safe settings to every component.
Produces: nothing (pure read).
Consumes: `.env` at process start.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    db_path: Path
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    redis_url: str | None
    groq_api_key: str | None
    gemini_api_key: str | None
    deepseek_api_key: str | None
    openrouter_api_key: str | None


def _get(name: str) -> str | None:
    v = os.environ.get(name)
    return v if v else None


def load() -> Config:
    load_dotenv(override=False)
    raw_db = os.environ.get("HYPHA_DB_PATH", "./hypha.db")
    db_path = Path(raw_db).expanduser().resolve()
    return Config(
        db_path=db_path,
        telegram_bot_token=_get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get("TELEGRAM_CHAT_ID"),
        redis_url=_get("REDIS_URL"),
        groq_api_key=_get("GROQ_API_KEY"),
        gemini_api_key=_get("GEMINI_API_KEY"),
        deepseek_api_key=_get("DEEPSEEK_API_KEY"),
        openrouter_api_key=_get("OPENROUTER_API_KEY"),
    )
