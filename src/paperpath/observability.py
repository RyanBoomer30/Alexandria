"""Call logging context. Stages set the roadmap id; clients attach it to each log row."""

from contextvars import ContextVar

current_roadmap_id: ContextVar[str | None] = ContextVar("current_roadmap_id", default=None)
