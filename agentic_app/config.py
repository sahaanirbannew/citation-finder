from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    max_iterations: int = 10
    max_hyperlinks_per_page: int = 8
    max_parallel_workers: int = 4
    request_timeout_seconds: int = 20
    max_request_retries: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("GEMINI_API_KEY is missing. Set it in the environment or .env file.")
        return cls(gemini_api_key=api_key)
