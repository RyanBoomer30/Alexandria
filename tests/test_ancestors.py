import pytest

from paperpath.domain.ancestors import (
    Budget,
    Candidate,
    CitationContext,
    CitationSection,
    ScoredCandidate,
    classify_section,
    compute_priority,
    expand_ancestors,
)
from paperpath.domain.models import PaperRole


def _scored(
    canonical_id: str,
    *,
    usefulness: int = 3,
    minutes: int = 30,
    role: PaperRole = PaperRole.FOUNDATIONAL,
    builds_on: bool = True,
) -> ScoredCandidate:
    return ScoredCandidate(
        candidate=Candidate(
            canonical_id=canonical_id,
            title=canonical_id,
            influential=True,
            contexts=(CitationContext(CitationSection.METHOD, "method section"),),
        ),
        builds_on=builds_on,
        builds_on_confidence=0.9 if builds_on else 0.1,
        introduced_topic_ids=("attention",) if builds_on else (),
        role=role,
        learner_usefulness=usefulness,
        reading_minutes=minutes,
    )


def test_method_citations_and_surveys_outrank_related_work() -> None:
    method = compute_priority(
        contexts=(CitationContext(CitationSection.METHOD, "method"),),
        influential=True,
        builds_on=True,
        builds_on_confidence=1,
        introduced_count=1,
        role=PaperRole.SURVEY,
        learner_usefulness=5,
        path_count=1,
    )
    related = compute_priority(
        contexts=(CitationContext(CitationSection.RELATED_WORK, "related work"),),
        influential=False,
        builds_on=False,
        builds_on_confidence=0.2,
        introduced_count=0,
        role=PaperRole.BACKGROUND,
        learner_usefulness=2,
        path_count=1,
    )
    assert method > related
    assert classify_section(["methodology"], "see section 3") is CitationSection.METHOD
    assert classify_section([], "In related work we discuss priors") is CitationSection.RELATED_WORK


def test_convergence_increases_priority() -> None:
    shared = dict(
        contexts=(CitationContext(CitationSection.METHOD, "method"),),
        influential=False,
        builds_on=True,
        builds_on_confidence=0.8,
        introduced_count=1,
        role=PaperRole.FOUNDATIONAL,
        learner_usefulness=3,
    )
    once = compute_priority(**shared, path_count=1)
    twice = compute_priority(**shared, path_count=2)
    assert twice == pytest.approx(once * 1.15)


async def test_best_first_respects_count_time_and_depth() -> None:
    tree = {
        "root": [_scored("a", usefulness=5, minutes=100), _scored("b", usefulness=4, minutes=100)],
        "a": [_scored("c", usefulness=3, minutes=10)],
        "b": [_scored("c", usefulness=3, minutes=10), _scored("d", usefulness=1, minutes=10)],
    }
    fetched: list[str] = []

    async def fetch(paper_id: str):
        fetched.append(paper_id)
        return tree.get(paper_id, [])

    selected = await expand_ancestors("root", fetch, Budget(max_papers=1, max_reading_minutes=500, max_depth=2))
    assert [item.canonical_id for item in selected] == ["a"]
    assert fetched == ["root"]

    fetched.clear()
    selected = await expand_ancestors("root", fetch, Budget(max_papers=5, max_reading_minutes=150, max_depth=2))
    assert [item.canonical_id for item in selected] == ["a"]

    fetched.clear()
    selected = await expand_ancestors("root", fetch, Budget(max_papers=5, max_reading_minutes=500, max_depth=1))
    assert {item.canonical_id for item in selected} == {"a", "b"}

    fetched.clear()
    selected = await expand_ancestors("root", fetch, Budget(max_papers=5, max_reading_minutes=500, max_depth=2))
    by_id = {item.canonical_id: item for item in selected}
    assert set(by_id) == {"a", "b", "c", "d"}
    assert by_id["c"].path_count == 2
    assert by_id["c"].depth == 2


async def test_a_single_paper_longer_than_the_budget_is_still_kept() -> None:
    async def fetch(paper_id: str):
        if paper_id == "root":
            return [_scored("classic", minutes=400), _scored("short", usefulness=1, minutes=10)]
        return []

    selected = await expand_ancestors("root", fetch, Budget(max_papers=5, max_reading_minutes=60, max_depth=2))
    assert [item.canonical_id for item in selected] == ["classic"]
