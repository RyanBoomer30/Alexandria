"""Resolve Wikipedia pages and earlier papers. Every URL comes from an API response."""

import logging

from paperpath.domain.models import Relation, Resource, ResourceType
from paperpath.judgments.catalog import WIKIPEDIA_MATCH
from paperpath.judgments.parse import NoulAnswer
from paperpath.pipeline.context import RunContext

logger = logging.getLogger(__name__)

_EXCERPT_CHARS = 400
_ATTRIBUTION = "Excerpt from the Wikipedia article, available under CC BY-SA."


class ResourceStage:
    name = "resources"

    async def run(self, ctx: RunContext) -> None:
        resources: list[Resource] = []
        for topic in ctx.topics:
            if not topic.included:
                continue
            article = await self._wikipedia(ctx, topic.id, topic.name, topic.usage_description)
            if article is not None:
                resources.append(article)
            resources.extend(self._papers(ctx, topic.id))
        ctx.resources = resources

    async def _wikipedia(self, ctx: RunContext, topic_id: str, name: str, usage: str) -> Resource | None:
        articles = await ctx.clients.wikipedia.search(name, limit=ctx.settings.wikipedia_candidates)
        for article in articles:
            answers = await ctx.clients.judgments.decide(
                questions=[WIKIPEDIA_MATCH],
                state={
                    "topic": name,
                    "usage": usage,
                    "article_title": article.title,
                    "article_lead": article.extract[:1000],
                },
                call_name="wikipedia_match",
            )
            verdict = answers.get("wikipedia_match")
            if not isinstance(verdict, NoulAnswer) or not verdict.yes:
                continue
            excerpt = article.extract[:_EXCERPT_CHARS].strip() or None
            return Resource(
                topic_id=topic_id,
                type=ResourceType.WIKIPEDIA,
                url=article.url,
                title=article.title,
                verified=True,
                match_confidence=verdict.probability,
                excerpt=excerpt,
                attribution=_ATTRIBUTION if excerpt else None,
            )
        logger.info("No verified Wikipedia page for %s", name)
        return None

    def _papers(self, ctx: RunContext, topic_id: str) -> list[Resource]:
        by_id = {item.canonical_id: item for item in ctx.ancestors}
        resources: list[Resource] = []
        seen: set[str] = set()
        for link in ctx.paper_topics:
            if link.topic_id != topic_id or link.relation != Relation.INTRODUCED:
                continue
            paper = by_id.get(link.paper_id)
            if paper is None or not paper.url or paper.url in seen:
                continue
            seen.add(paper.url)
            resources.append(
                Resource(
                    topic_id=topic_id,
                    type=ResourceType.PAPER,
                    url=paper.url,
                    title=paper.title,
                    verified=True,
                    match_confidence=link.confidence,
                )
            )
        return resources
