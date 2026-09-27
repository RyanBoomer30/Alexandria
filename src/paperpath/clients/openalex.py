"""OpenAlex reference lists, used when Semantic Scholar has no bibliography."""

import httpx

from paperpath.clients.http import RateLimiter, request_with_retries
from paperpath.clients.semantic_scholar import canonical_work_id
from paperpath.domain.ancestors import Candidate
from paperpath.domain.arxiv import ArxivId
from paperpath.errors import UpstreamError

_API = "https://api.openalex.org"


class OpenAlexClient:
    def __init__(self, client: httpx.AsyncClient, *, mailto: str) -> None:
        self._client = client
        self._limiter = RateLimiter(0.2)
        self._mailto = mailto

    async def references_for_arxiv(self, arxiv_id: ArxivId) -> list[Candidate]:
        work = await self._get(f"{_API}/works/https://arxiv.org/abs/{arxiv_id.base}")
        if not isinstance(work, dict):
            return []
        referenced = work.get("referenced_works") or []
        if not referenced:
            return []
        # OpenAlex accepts a filter of up to about 50 ids. Chunk to stay under that.
        candidates: list[Candidate] = []
        for start in range(0, len(referenced), 40):
            chunk = referenced[start : start + 40]
            short = [item.rstrip("/").split("/")[-1] for item in chunk]
            payload = await self._get(
                f"{_API}/works",
                params={"filter": f"openalex_id:{'|'.join(short)}", "per-page": len(short)},
            )
            if not isinstance(payload, dict):
                continue
            for item in payload.get("results") or []:
                candidate = candidate_from_openalex(item)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    async def _get(self, url: str, params: dict | None = None) -> object | None:
        query = dict(params or {})
        if self._mailto:
            query["mailto"] = self._mailto
        try:
            response = await request_with_retries(
                self._client,
                "GET",
                url,
                limiter=self._limiter,
                params=query,
            )
        except UpstreamError:
            return None
        return response.json()


def candidate_from_openalex(item: dict) -> Candidate | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    ids = item.get("ids") or {}
    arxiv_id = _arxiv_from_ids(ids)
    doi = ids.get("doi")
    if isinstance(doi, str) and doi.startswith("https://doi.org/"):
        doi = doi.removeprefix("https://doi.org/")
    try:
        canonical = canonical_work_id(
            arxiv_id=arxiv_id,
            doi=doi if isinstance(doi, str) else None,
            openalex_id=item.get("id"),
        )
    except ValueError:
        return None
    location = item.get("primary_location") or {}
    url = location.get("landing_page_url") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None)
    abstract = _abstract(item.get("abstract_inverted_index"))
    pages = _pages(item.get("biblio") or {})
    return Candidate(
        canonical_id=canonical,
        title=title,
        year=item.get("publication_year"),
        arxiv_id=arxiv_id,
        abstract=abstract,
        url=url,
        page_count=pages,
    )


def _arxiv_from_ids(ids: dict) -> str | None:
    for key in ("arxiv", "arXiv"):
        value = ids.get(key)
        if isinstance(value, str) and value:
            return value.removeprefix("https://arxiv.org/abs/")
    return None


def _abstract(inverted: object) -> str:
    if not isinstance(inverted, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int):
                positions.append((index, str(word)))
    positions.sort()
    return " ".join(word for _, word in positions)


def _pages(biblio: dict) -> int | None:
    first = biblio.get("first_page")
    last = biblio.get("last_page")
    try:
        if first is not None and last is not None:
            count = int(last) - int(first) + 1
            return count if count > 0 else None
    except (TypeError, ValueError):
        return None
    return None
