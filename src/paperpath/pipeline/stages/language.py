"""Frontier-model stages: topic extraction, edge proposals, and explanations."""

import json
import logging

from pydantic import BaseModel, Field

from paperpath.domain.models import Edge, EdgeSource, Topic
from paperpath.domain.text import allocate_id, prompt_context
from paperpath.errors import PaperPathError
from paperpath.pipeline.context import RunContext
from paperpath.pipeline.prompts import EDGES_SYSTEM, EXPLAIN_SYSTEM, EXTRACT_SYSTEM

logger = logging.getLogger(__name__)


class _ExtractedTopic(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    usage_description: str = ""
    locations: list[str] = Field(default_factory=list)
    related_references: list[str] = Field(default_factory=list)


class _Extraction(BaseModel):
    topics: list[_ExtractedTopic] = Field(default_factory=list)


class _ProposedEdge(BaseModel):
    prerequisite: str
    dependent: str


class _EdgeProposal(BaseModel):
    edges: list[_ProposedEdge] = Field(default_factory=list)


class _Explanation(BaseModel):
    topic_name: str
    why_it_matters: str


class _Explanations(BaseModel):
    explanations: list[_Explanation] = Field(default_factory=list)


class TopicExtractionStage:
    name = "topic_extraction"

    async def run(self, ctx: RunContext) -> None:
        paper = ctx.require_paper()
        sections = [(section.level, section.title, section.text) for section in ctx.sections]
        user = prompt_context(paper.title, paper.abstract, sections, ctx.settings.max_paper_chars)
        raw = await ctx.clients.frontier.complete_json(
            system=EXTRACT_SYSTEM,
            user=user,
            call_name="topic_extraction",
        )
        parsed = _Extraction.model_validate(raw)
        used: set[str] = set()
        topics: list[Topic] = []
        for item in parsed.topics:
            name = item.name.strip()
            if not name:
                continue
            topics.append(
                Topic(
                    id=allocate_id(name, used),
                    name=name,
                    aliases=[alias.strip() for alias in item.aliases if alias.strip()],
                    usage_description=item.usage_description.strip(),
                    locations=[loc.strip() for loc in item.locations if loc.strip()],
                    related_references=[ref.strip() for ref in item.related_references if ref.strip()],
                )
            )
        if not topics:
            raise PaperPathError(f"No topics were extracted from {paper.key}.")
        if not 15 <= len(topics) <= 50:
            logger.warning("Extracted %s topics from %s; the target band is 15 to 50", len(topics), paper.key)
        ctx.topics = topics


class EdgeProposalStage:
    name = "edge_proposal"

    async def run(self, ctx: RunContext) -> None:
        listing = [
            {"name": topic.name, "usage": topic.usage_description, "essentiality": topic.essentiality}
            for topic in ctx.topics
        ]
        raw = await ctx.clients.frontier.complete_json(
            system=EDGES_SYSTEM,
            user=json.dumps({"topics": listing}, ensure_ascii=False),
            call_name="edge_proposal",
        )
        parsed = _EdgeProposal.model_validate(raw)
        edges: list[Edge] = []
        seen: set[tuple[str, str]] = set()
        for item in parsed.edges:
            prerequisite = _match(item.prerequisite, ctx.topics)
            dependent = _match(item.dependent, ctx.topics)
            if prerequisite is None or dependent is None or prerequisite.id == dependent.id:
                continue
            key = (prerequisite.id, dependent.id)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                Edge(
                    prerequisite_id=prerequisite.id,
                    dependent_id=dependent.id,
                    confidence=0.0,
                    source=EdgeSource.PROPOSED,
                    kept=False,
                )
            )
        ctx.edges = edges


class ExplanationStage:
    name = "explanations"

    async def run(self, ctx: RunContext) -> None:
        paper = ctx.require_paper()
        payload = {
            "paper_title": paper.title,
            "abstract": paper.abstract,
            "topics": [
                {
                    "name": topic.name,
                    "usage": topic.usage_description,
                    "essentiality": topic.essentiality,
                    "difficulty": topic.difficulty,
                }
                for topic in ctx.topics
                if topic.included
            ],
        }
        try:
            raw = await ctx.clients.frontier.complete_json(
                system=EXPLAIN_SYSTEM,
                user=json.dumps(payload, ensure_ascii=False),
                call_name="explanations",
            )
            parsed = _Explanations.model_validate(raw)
        except Exception:
            logger.warning("Explanation call failed for %s; keeping usage descriptions", paper.key, exc_info=True)
            parsed = _Explanations()
        by_name = {item.topic_name.strip().lower(): item.why_it_matters.strip() for item in parsed.explanations}
        updated: list[Topic] = []
        for topic in ctx.topics:
            why = by_name.get(topic.name.lower()) or topic.usage_description
            updated.append(topic.model_copy(update={"why_it_matters": why}))
        ctx.topics = updated


def _match(name: str, topics: list[Topic]) -> Topic | None:
    needle = name.strip().lower()
    if not needle:
        return None
    for topic in topics:
        names = {topic.name.lower(), *(alias.lower() for alias in topic.aliases)}
        if needle in names:
            return topic
    return None
