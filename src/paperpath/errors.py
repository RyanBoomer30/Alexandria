"""Errors the API layer maps onto HTTP status codes."""


class PaperPathError(Exception):
    """Base error for expected pipeline failures."""


class ConfigurationError(PaperPathError):
    """A required API key or backend is missing."""


class IngestionError(PaperPathError):
    """The arXiv id could not be resolved or read."""


class NotFoundError(PaperPathError):
    """The roadmap or paper is not in the store."""


class NotReadyError(PaperPathError):
    """The roadmap exists but generation has not finished."""


class UpstreamError(PaperPathError):
    """An external API failed after retries."""
