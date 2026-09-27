"""Jev judgments for essentiality, difficulty, and proposed prerequisite edges."""

import logging

from paperpath.domain.models import Edge, EdgeSource, Essentiality
from paperpath.judgments.catalog import DIFFICULTY, ESSENTIALITY, PREREQUISITE, USER_KNOWS
from paperpath.judgments.parse import ChoiceAnswer, NoulAnswer, ScoreAnswer
from paperpath.pipeline.context import RunContext

logger = logging.getLogger(__name__)


class JudgmentStage:
    name = "judgments"

    async def run(self, ctx: RunContext) -> None:
        paper = ctx.require_paper()
        updated = []
        for topic in ctx.topics:
            state = {
                "paper_title": paper.title,
                "paper_abstract": paper.abstract,
                "topic": topic.name,
                "aliases": topic.aliases,
                "usage": topic.usage_description,
            }
            answers = await ctx.clients.judgments.decide(
                questions=[ESSENTIALITY, DIFFICULTY],
                state=state,
                call_name="topic_judgments",
            )
            essentiality = _essentiality(answers.get("essentiality"))
            difficulty = _difficulty(answers.get("difficulty"))
            updated.append(topic.model_copy(update={"essentiality": essentiality, "difficulty": difficulty}))
        ctx.topics = updated


class EdgeVerificationStage:
    name = "edge_verification"

    async def run(self, ctx: RunContext) -> None:
        paper = ctx.require_paper()
        by_id = {topic.id: topic for topic in ctx.topics}
        verified: list[Edge] = []
        for edge in ctx.edges:
            prerequisite = by_id.get(edge.prerequisite_id)
            dependent = by_id.get(edge.dependent_id)
            if prerequisite is None or dependent is None:
                continue
            answers = await ctx.clients.judgments.decide(
                questions=[PREREQUISITE],
                state={
                    "paper_title": paper.title,
                    "topic_a": {"name": prerequisite.name, "usage": prerequisite.usage_description},
                    "topic_b": {"name": dependent.name, "usage": dependent.usage_description},
                },
                call_name="prerequisite",
            )
            answer = answers.get("prerequisite")
            if not isinstance(answer, NoulAnswer):
                continue
            verified.append(
                edge.model_copy(
                    update={
                        "confidence": answer.probability,
                        "source": EdgeSource.VERIFIED,
                        "kept": False,
                        "drop_reason": None if answer.yes else "not_prerequisite",
                    }
                )
            )
        ctx.edges = verified


async def topics_the_reader_knows(ctx: RunContext, answers: list[tuple[str, str, str]]) -> list[str]:
    """Score diagnostic replies. Each tuple is (topic_id, question, answer)."""
    known: list[str] = []
    by_id = {topic.id: topic for topic in ctx.topics}
    for topic_id, question, reply in answers:
        topic = by_id.get(topic_id)
        if topic is None or not reply.strip():
            continue
        judged = await ctx.clients.judgments.decide(
            questions=[USER_KNOWS],
            state={"topic": topic.name, "usage": topic.usage_description, "question": question, "answer": reply},
            call_name="user_knows",
        )
        answer = judged.get("user_knows")
        if isinstance(answer, NoulAnswer) and answer.yes:
            known.append(topic_id)
    return known


def _essentiality(answer: object) -> Essentiality:
    if isinstance(answer, ChoiceAnswer):
        try:
            return Essentiality(answer.choice)
        except ValueError:
            logger.warning("Unknown essentiality label %s", answer.choice)
    return Essentiality.SUPPORTING


def _difficulty(answer: object) -> int:
    if isinstance(answer, ScoreAnswer):
        return min(5, max(1, answer.level))
    return 3
