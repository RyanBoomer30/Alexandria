"""Wikipedia search and lead extracts. URLs come from the API, never from a model."""

import httpx

from paperpath.clients.http import RateLimiter, request_with_retries
from paperpath.errors import UpstreamError

_API = "https://en.wikipedia.org/w/api.php"


class WikipediaArticle:
    def __init__(self, title: str, url: str, extract: str) -> None:
        self.title = title
        self.url = url
        self.extract = extract


class WikipediaClient:
    def __init__(self, client: httpx.AsyncClient, *, user_agent: str) -> None:
        self._client = client
        self._limiter = RateLimiter(0.2)
        self._headers = {"User-Agent": user_agent}

    async def search(self, query: str, *, limit: int) -> list[WikipediaArticle]:
        try:
            response = await request_with_retries(
                self._client,
                "GET",
                _API,
                limiter=self._limiter,
                headers=self._headers,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": limit,
                    "format": "json",
                },
            )
        except UpstreamError:
            return []
        payload = response.json()
        hits = ((payload.get("query") or {}).get("search") or []) if isinstance(payload, dict) else []
        articles: list[WikipediaArticle] = []
        for hit in hits:
            title = hit.get("title")
            if not title:
                continue
            article = await self.lead(title)
            if article is not None:
                articles.append(article)
        return articles

    async def lead(self, title: str) -> WikipediaArticle | None:
        try:
            response = await request_with_retries(
                self._client,
                "GET",
                _API,
                limiter=self._limiter,
                headers=self._headers,
                params={
                    "action": "query",
                    "prop": "extracts|info",
                    "inprop": "url",
                    "exintro": 1,
                    "explaintext": 1,
                    "redirects": 1,
                    "titles": title,
                    "format": "json",
                },
            )
        except UpstreamError:
            return None
        payload = response.json()
        pages = ((payload.get("query") or {}).get("pages") or {}) if isinstance(payload, dict) else {}
        for page in pages.values():
            if page.get("missing") is not None or page.get("pageid", 0) < 0:
                continue
            page_title = page.get("title") or title
            url = page.get("fullurl") or f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"
            extract = (page.get("extract") or "").strip()
            return WikipediaArticle(title=page_title, url=url, extract=extract)
        return None
