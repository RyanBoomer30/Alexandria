"""Best-first selection of earlier papers under a count, time, and depth budget.

Jev scores a candidate. This module only combines those scores with citation
signals and decides which papers fit. Shared ancestors collapse to one node,
and reaching the same paper from several parents raises its priority.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

from paperpath.domain.models import PaperRole

_SECTION_WEIGHT = {
    "method": 1.0,
    "experiments": 0.55,
    "introduction": 0.4,
    "related_work": 0.2,
    "other": 0.3,
}
_ROLE_MULTIPLIER = {
    PaperRole.FOUNDATIONAL: 1.0,
    PaperRole.SURVEY: 1.3,
    PaperRole.BENCHMARK: 0.75,
    PaperRole.BACKGROUND: 0.6,
}


class CitationSection(StrEnum):
    METHOD = "method"
    EXPERIMENTS = "experiments"
    INTRODUCTION = "introduction"
    RELATED_WORK = "related_work"
    OTHER = "other"


@dataclass(frozen=True)
class Budget:
    max_papers: int = 8
    max_reading_minutes: int = 240
    max_depth: int = 2


@dataclass(frozen=True)
class CitationContext:
    section: CitationSection
    text: str


@dataclass(frozen=True)
class Candidate:
    canonical_id: str
    title: str
    year: int | None = None
    arxiv_id: str | None = None
    abstract: str = ""
    url: str | None = None
    influential: bool = False
    contexts: tuple[CitationContext, ...] = ()
    page_count: int | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: Candidate
    builds_on: bool
    builds_on_confidence: float
    introduced_topic_ids: tuple[str, ...] = ()
    develops_topic_ids: tuple[str, ...] = ()
    role: PaperRole = PaperRole.BACKGROUND
    learner_usefulness: int = 1
    reading_minutes: int = 30
    base_priority: float = 0.0


@dataclass
class SelectedAncestor:
    scored: ScoredCandidate
    depth: int
    path_count: int = 1
    priority: float = 0.0
    via: list[str] = field(default_factory=list)

    @property
    def canonical_id(self) -> str:
        return self.scored.candidate.canonical_id


def classify_section(intents: list[str], context: str) -> CitationSection:
    intent_names = {item.lower() for item in intents}
    if "methodology" in intent_names:
        return CitationSection.METHOD
    text = context.lower()
    if "related work" in text or "prior work" in text:
        return CitationSection.RELATED_WORK
    if "experiment" in text or "result" in intent_names:
        return CitationSection.EXPERIMENTS
    if "introduction" in text:
        return CitationSection.INTRODUCTION
    if "background" in intent_names:
        return CitationSection.RELATED_WORK
    return CitationSection.OTHER


def estimate_reading_minutes(page_count: int | None, usefulness: int) -> int:
    pages = page_count or 12
    usefulness = min(5, max(1, usefulness))
    return max(10, round(pages * 3 * (0.8 + 0.1 * usefulness)))


def compute_priority(
    *,
    contexts: tuple[CitationContext, ...],
    influential: bool,
    builds_on: bool,
    builds_on_confidence: float,
    introduced_count: int,
    role: PaperRole,
    learner_usefulness: int,
    path_count: int,
) -> float:
    """Rank a candidate. Method citations outrank related work, and surveys get a boost."""
    if contexts:
        section = max(_SECTION_WEIGHT[item.section] for item in contexts)
        frequency = min(len(contexts), 5) / 5
    else:
        section = 0.15
        frequency = 0.0
    signal = 0.35 * section + 0.10 * frequency + (0.15 if influential else 0.0)
    builds = 0.30 * builds_on_confidence if builds_on else 0.0
    introduced = 0.20 * min(introduced_count, 3) / 3
    usefulness = 0.20 * (min(5, max(1, learner_usefulness)) / 5)
    convergence = 1 + 0.15 * (max(1, path_count) - 1)
    return (signal + builds + introduced + usefulness) * _ROLE_MULTIPLIER[role] * convergence


def paper_blurb(*, title: str, role: PaperRole, topic_names: list[str], target_title: str) -> str:
    role_text = {
        PaperRole.FOUNDATIONAL: "a foundational method",
        PaperRole.SURVEY: "a survey or tutorial",
        PaperRole.BENCHMARK: "a benchmark or dataset",
        PaperRole.BACKGROUND: "background reading",
    }[role]
    if topic_names:
        topics = ", ".join(topic_names)
        return (
            f"{title} is {role_text} behind {target_title}. "
            f"It is the place to meet {topics}."
        )
    return f"{title} is {role_text} behind {target_title}."


FetchScored = Callable[[str], Awaitable[list[ScoredCandidate]]]


async def expand_ancestors(
    root_id: str,
    fetch_scored: FetchScored,
    budget: Budget,
) -> list[SelectedAncestor]:
    """Walk earlier papers best-first until the paper count, reading time, or depth runs out.

    The first paper is kept even when it alone exceeds the reading-time budget, so a
    single long classic is not replaced by silence. Later papers stop the walk when
    they no longer fit. Papers past max_depth are not fetched.
    """
    if budget.max_papers <= 0 or budget.max_depth <= 0:
        return []

    selected: dict[str, SelectedAncestor] = {}
    waiting: dict[str, SelectedAncestor] = {}
    minutes = 0

    def consider(parent_id: str, scored: ScoredCandidate, depth: int) -> None:
        if scored.candidate.canonical_id == root_id:
            return
        existing = selected.get(scored.candidate.canonical_id)
        if existing is not None:
            existing.path_count += 1
            existing.priority = _priority(existing.scored, existing.path_count)
            if parent_id not in existing.via:
                existing.via.append(parent_id)
            return
        queued = waiting.get(scored.candidate.canonical_id)
        if queued is not None:
            queued.path_count += 1
            queued.priority = _priority(queued.scored, queued.path_count)
            queued.depth = min(queued.depth, depth)
            if parent_id not in queued.via:
                queued.via.append(parent_id)
            return
        item = SelectedAncestor(
            scored=scored,
            depth=depth,
            path_count=1,
            priority=_priority(scored, 1),
            via=[parent_id],
        )
        waiting[item.canonical_id] = item

    for scored in await fetch_scored(root_id):
        consider(root_id, scored, depth=1)

    while waiting and len(selected) < budget.max_papers:
        choice = max(waiting.values(), key=lambda item: (item.priority, -item.depth, item.canonical_id))
        del waiting[choice.canonical_id]
        if choice.depth > budget.max_depth:
            continue
        reading = choice.scored.reading_minutes
        if selected and minutes + reading > budget.max_reading_minutes:
            break
        selected[choice.canonical_id] = choice
        minutes += reading
        if minutes > budget.max_reading_minutes or len(selected) >= budget.max_papers:
            break
        if choice.depth >= budget.max_depth:
            continue
        for scored in await fetch_scored(choice.canonical_id):
            consider(choice.canonical_id, scored, depth=choice.depth + 1)

    return sorted(selected.values(), key=lambda item: (-item.priority, item.depth, item.canonical_id))


def _priority(scored: ScoredCandidate, path_count: int) -> float:
    return compute_priority(
        contexts=scored.candidate.contexts,
        influential=scored.candidate.influential,
        builds_on=scored.builds_on,
        builds_on_confidence=scored.builds_on_confidence,
        introduced_count=len(scored.introduced_topic_ids),
        role=scored.role,
        learner_usefulness=scored.learner_usefulness,
        path_count=path_count,
    )
