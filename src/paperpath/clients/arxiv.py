"""Fetch metadata and source from the public arXiv API."""

import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from paperpath.clients.http import RateLimiter, request_with_retries
from paperpath.domain.arxiv import ArxivId
from paperpath.domain.models import Paper, SourceType
from paperpath.errors import IngestionError

_ATOM = "http://www.w3.org/2005/Atom"
_API = "https://export.arxiv.org/api/query"


class ArxivClient:
    def __init__(self, client: httpx.AsyncClient, *, min_interval: float, user_agent: str) -> None:
        self._client = client
        self._limiter = RateLimiter(min_interval)
        self._headers = {"User-Agent": user_agent}

    async def fetch_metadata(self, arxiv_id: ArxivId) -> Paper:
        response = await request_with_retries(
            self._client,
            "GET",
            _API,
            limiter=self._limiter,
            params={"id_list": arxiv_id.canonical, "max_results": 1},
            headers=self._headers,
        )
        return parse_atom(response.text, requested=arxiv_id)

    async def fetch_source(self, arxiv_id: ArxivId) -> bytes | None:
        url = f"https://arxiv.org/e-print/{arxiv_id.canonical}"
        response = await self._optional("GET", url)
        if response is None:
            return None
        return response.content

    async def fetch_html(self, arxiv_id: ArxivId) -> str | None:
        url = f"https://arxiv.org/html/{arxiv_id.canonical}"
        response = await self._optional("GET", url)
        if response is None:
            return None
        return response.text

    async def fetch_pdf(self, arxiv_id: ArxivId) -> bytes | None:
        url = f"https://arxiv.org/pdf/{arxiv_id.canonical}.pdf"
        response = await self._optional("GET", url)
        if response is None:
            return None
        return response.content

    async def _optional(self, method: str, url: str) -> httpx.Response | None:
        await self._limiter.wait()
        try:
            response = await self._client.request(method, url, headers=self._headers)
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        return response


def parse_atom(xml_text: str, *, requested: ArxivId) -> Paper:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise IngestionError("arXiv returned metadata that is not valid XML.") from exc
    entry = root.find(f"{{{_ATOM}}}entry")
    if entry is None or entry.find(f"{{{_ATOM}}}title") is None:
        raise IngestionError(f"arXiv has no record for {requested.canonical}.")

    title = _text(entry, "title")
    abstract = _text(entry, "summary")
    authors = [
        name.text.strip()
        for author in entry.findall(f"{{{_ATOM}}}author")
        if (name := author.find(f"{{{_ATOM}}}name")) is not None and name.text
    ]
    categories = [
        term
        for category in entry.findall(f"{{{_ATOM}}}category")
        if (term := category.attrib.get("term"))
    ]
    raw_id = _text(entry, "id")
    resolved = _version_from_abs_url(raw_id) or requested
    published = _timestamp(entry, "published")
    return Paper(
        key=resolved.canonical,
        arxiv_id=resolved.base,
        version=resolved.version,
        title=title,
        abstract=abstract,
        authors=authors,
        categories=categories,
        source_type=SourceType.METADATA_ONLY,
        fetched_at=datetime.now().astimezone(),
        published=published,
    )


def _text(entry: ET.Element, tag: str) -> str:
    node = entry.find(f"{{{_ATOM}}}{tag}")
    if node is None or node.text is None:
        return ""
    return " ".join(node.text.split())


def _timestamp(entry: ET.Element, tag: str) -> datetime | None:
    raw = _text(entry, tag)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            return parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None


def _version_from_abs_url(url: str) -> ArxivId | None:
    from paperpath.domain.arxiv import parse_arxiv_id

    try:
        return parse_arxiv_id(url)
    except IngestionError:
        return None
