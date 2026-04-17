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


def load() -> Config:
    raise NotImplementedError("M1: load .env and return Config")
