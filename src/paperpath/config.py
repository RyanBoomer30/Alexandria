"""Runtime settings. Environment variables use the PAPERPATH_ prefix."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAPERPATH_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/paperpath.db"
    data_dir: Path = Path("./data")
    contact_email: str = ""
    log_level: str = "INFO"
    inline_jobs: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # One OpenRouter key covers chat completions and the Jev Decisions API.
    openrouter_api_key: str = ""
    frontier_base_url: str = "https://openrouter.ai/api/v1"
    frontier_model: str = "openai/gpt-4.1"

    jev_base_url: str = "https://openrouter.ai/api/alpha"
    jev_model: str = "typesafe/jev-1.13"
    jev_fallback: Literal["frontier", "none"] = "frontier"
    jev_max_questions: int = 16
    noul_yes_threshold: float = 0.7

    s2_api_key: str = ""
    s2_min_interval_seconds: float = 1.0
    openalex_mailto: str = ""
    arxiv_min_interval_seconds: float = 3.0
    http_timeout_seconds: float = 60.0

    confidence_threshold: float = 0.7
    max_topic_depth: int = 4
    difficulty_floor: int = 1
    ancestor_paper_budget: int = 8
    ancestor_reading_minutes: int = 240
    ancestor_max_depth: int = 2
    diagnostic_questions: int = 8
    max_paper_chars: int = 60_000
    wikipedia_candidates: int = 3

    app_name: str = "PaperPath"

    @property
    def user_agent(self) -> str:
        contact = self.contact_email or "unset-contact"
        return f"PaperPath/0.1 (mailto:{contact})"

    @property
    def frontier_configured(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def jev_configured(self) -> bool:
        return bool(self.openrouter_api_key)
