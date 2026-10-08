"""Semantic Scholar reference lists, including influential-citation flags."""

import re

import httpx

from paperpath.clients.http import RateLimiter, request_with_retries
from paperpath.domain.ancestors import Candidate, CitationContext, classify_section
from paperpath.domain.arxiv import ArxivId
from paperpath.errors import UpstreamError

_API = "https://api.semanticscholar.org/graph/v1"
_FIELDS = ",".join(
    [
        "isInfluential",
        "contexts",
        "intents",
        "citedPaper.paperId",
        "citedPaper.title",
        "citedPaper.abstract",
        "citedPaper.year",
        "citedPaper.externalIds",
        "citedPaper.url",
    ]
)


class SemanticScholarClient:
    def __init__(self, client: httpx.AsyncClient, *, api_key: str, min_interval: float) -> None:
        self._client = client
        self._limiter = RateLimiter(min_interval)
        self._headers = {"x-api-key": api_key} if api_key else {}

    async def references_for_arxiv(self, arxiv_id: ArxivId) -> list[Candidate]:
        return await self._references(f"ARXIV:{arxiv_id.base}")

    async def references_for_canonical(self, canonical_id: str) -> list[Candidate]:
        if canonical_id.startswith("arxiv:"):
            return await self._references(f"ARXIV:{canonical_id.removeprefix('arxiv:')}")
        if canonical_id.startswith("s2:"):
            return await self._references(canonical_id.removeprefix("s2:"))
        if canonical_id.startswith("doi:"):
            return await self._references(f"DOI:{canonical_id.removeprefix('doi:')}")
        return []

    async def _references(self, paper_id: str) -> list[Candidate]:
        url = f"{_API}/paper/{paper_id}/references"
        try:
            response = await request_with_retries(
                self._client,
                "GET",
                url,
                limiter=self._limiter,
                params={"fields": _FIELDS, "limit": 100},
                headers=self._headers,
            )
        except UpstreamError:
            return []
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        candidates: list[Candidate] = []
        for item in payload.get("data") or []:
            candidate = candidate_from_s2(item)
            if candidate is not None:
                candidates.append(candidate)
        return candidates


def candidate_from_s2(item: dict) -> Candidate | None:
    cited = item.get("citedPaper") or {}
    title = (cited.get("title") or "").strip()
    if not title:
        return None
    external = cited.get("externalIds") or {}
    arxiv_id = external.get("ArXiv")
    doi = external.get("DOI")
    s2_id = cited.get("paperId")
    try:
        canonical = canonical_work_id(arxiv_id=arxiv_id, doi=doi, s2_id=s2_id)
    except ValueError:
        return None
    contexts = []
    intents = list(item.get("intents") or [])
    for text in item.get("contexts") or []:
        if not isinstance(text, str) or not text.strip():
            continue
        contexts.append(CitationContext(section=classify_section(intents, text), text=text.strip()))
    url = cited.get("url")
    if arxiv_id and not url:
        url = f"https://arxiv.org/abs/{arxiv_id}"
    return Candidate(
        canonical_id=canonical,
        title=title,
        year=cited.get("year"),
        arxiv_id=str(arxiv_id) if arxiv_id else None,
        abstract=(cited.get("abstract") or "").strip(),
        url=url,
        influential=bool(item.get("isInfluential")),
        contexts=tuple(contexts),
    )


def normalize_arxiv_base(arxiv_id: str) -> str:
    text = arxiv_id.strip()
    text = re.sub(r"^https?://arxiv\.org/abs/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"v\d+$", "", text, flags=re.IGNORECASE)
    if text[:4].isdigit():
        return text.lower()
    archive, _, number = text.partition("/")
    return f"{archive.lower()}/{number}" if number else text.lower()


def canonical_work_id(
    *,
    arxiv_id: str | None = None,
    doi: str | None = None,
    s2_id: str | None = None,
    openalex_id: str | None = None,
) -> str:
    """Prefer arXiv, then DOI, so the same work merges across Semantic Scholar and OpenAlex."""
    if arxiv_id:
        return f"arxiv:{normalize_arxiv_base(arxiv_id)}"
    if doi:
        return f"doi:{doi.lower()}"
    if s2_id:
        return f"s2:{s2_id}"
    if openalex_id:
        token = openalex_id.rstrip("/").split("/")[-1]
        return f"openalex:{token}"
    raise ValueError("A reference needs an arXiv id, DOI, Semantic Scholar id, or OpenAlex id.")
