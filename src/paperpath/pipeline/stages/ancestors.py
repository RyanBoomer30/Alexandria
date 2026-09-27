"""Select earlier papers best-first and cache their reference lists and scores."""

import hashlib
import json

from paperpath.domain.ancestors import (
    Budget,
    Candidate,
    CitationContext,
    CitationSection,
    ScoredCandidate,
    SelectedAncestor,
    compute_priority,
    estimate_reading_minutes,
    expand_ancestors,
    paper_blurb,
)
from paperpath.domain.models import AncestorPaper, PaperLink, PaperRole, PaperTopic, Relation
from paperpath.judgments.catalog import BUILDS_ON, LEARNER_USEFULNESS, PAPER_ROLE, introduced_question
from paperpath.judgments.parse import ChoiceAnswer, NoulAnswer, ScoreAnswer
from paperpath.pipeline.context import RunContext


class AncestorStage:
    name = "ancestors"

    async def run(self, ctx: RunContext) -> None:
        paper = ctx.require_paper()
        budget = _budget(ctx)
        selected = await expand_ancestors(paper.work_id, lambda paper_id: self._fetch_scored(ctx, paper_id), budget)
        self._write(ctx, selected, parent_depth=0)

    async def expand_one(self, ctx: RunContext, canonical_id: str) -> None:
        """Fetch the next layer of predecessors for one paper the reader opened."""
        parent = next((item for item in ctx.ancestors if item.canonical_id == canonical_id), None)
        if parent is None:
            return
        parent.expanded = True
        if parent.depth >= ctx.settings.ancestor_max_depth:
            return
        budget = Budget(
            max_papers=ctx.settings.ancestor_paper_budget,
            max_reading_minutes=ctx.settings.ancestor_reading_minutes,
            max_depth=1,
        )
        selected = await expand_ancestors(canonical_id, lambda paper_id: self._fetch_scored(ctx, paper_id), budget)
        self._write(ctx, selected, parent_depth=parent.depth)

    async def _fetch_scored(self, ctx: RunContext, canonical_id: str) -> list[ScoredCandidate]:
        candidates = await self._candidates(ctx, canonical_id)
        target = ctx.require_paper().work_id
        scored: list[ScoredCandidate] = []
        for candidate in candidates:
            if candidate.canonical_id in {target, canonical_id}:
                continue
            scored.append(await self._score(ctx, candidate))
        return scored

    async def _candidates(self, ctx: RunContext, canonical_id: str) -> list[Candidate]:
        cached = ctx.store.get_references(canonical_id)
        if cached is not None:
            return [candidate_from_dict(item) for item in cached]
        if canonical_id.startswith("arxiv:"):
            from paperpath.domain.arxiv import ArxivId

            base = canonical_id.removeprefix("arxiv:")
            candidates = await ctx.clients.scholar.references_for_arxiv(ArxivId(base=base))
            if not candidates:
                candidates = await ctx.clients.openalex.references_for_arxiv(ArxivId(base=base))
        else:
            candidates = await ctx.clients.scholar.references_for_canonical(canonical_id)
        ctx.store.put_references(canonical_id, [candidate_to_dict(item) for item in candidates])
        return candidates

    async def _score(self, ctx: RunContext, candidate: Candidate) -> ScoredCandidate:
        paper = ctx.require_paper()
        topic_hash = _topic_hash(ctx)
        cached = ctx.store.get_judgment(paper.work_id, candidate.canonical_id)
        if cached and cached.get("topic_hash") == topic_hash:
            return scored_from_cache(candidate, cached)

        state = {
            "target_title": paper.title,
            "target_abstract": paper.abstract,
            "citation_contexts": [item.text for item in candidate.contexts],
            "candidate_title": candidate.title,
            "candidate_abstract": candidate.abstract,
            "topics": [{"id": topic.id, "name": topic.name, "usage": topic.usage_description} for topic in ctx.topics],
            "roadmap_topics": [topic.name for topic in ctx.topics if topic.included],
        }
        overview = await ctx.clients.judgments.decide(
            questions=[BUILDS_ON, PAPER_ROLE, LEARNER_USEFULNESS],
            state=state,
            call_name="ancestor_overview",
        )
        introduced = await self._introduced(ctx, state)
        builds = overview.get("builds_on")
        builds_on = isinstance(builds, NoulAnswer) and builds.yes
        builds_confidence = builds.probability if isinstance(builds, NoulAnswer) else 0.0
        role = _role(overview.get("role"))
        usefulness_answer = overview.get("usefulness")
        usefulness = usefulness_answer.level if isinstance(usefulness_answer, ScoreAnswer) else 3
        reading = estimate_reading_minutes(candidate.page_count, usefulness)
        scores = {
            "topic_hash": topic_hash,
            "builds_on": builds_on,
            "builds_on_confidence": builds_confidence,
            "introduced_topic_ids": introduced,
            "role": role.value,
            "learner_usefulness": usefulness,
            "reading_minutes": reading,
        }
        model_name = ctx.settings.jev_model if ctx.settings.jev_configured else ctx.settings.frontier_model
        ctx.store.put_judgment(paper.work_id, candidate.canonical_id, scores, model_name)
        return scored_from_cache(candidate, scores)

    async def _introduced(self, ctx: RunContext, state: dict) -> list[str]:
        found: list[str] = []
        size = max(1, ctx.settings.jev_max_questions)
        topics = [topic for topic in ctx.topics if topic.included]
        for start in range(0, len(topics), size):
            batch = topics[start : start + size]
            questions = [introduced_question(topic.id, topic.name) for topic in batch]
            answers = await ctx.clients.judgments.decide(
                questions=questions,
                state=state,
                call_name="ancestor_introduced",
            )
            for topic in batch:
                answer = answers.get(f"introduced:{topic.id}")
                if isinstance(answer, NoulAnswer) and answer.yes:
                    found.append(topic.id)
        return found

    def _write(self, ctx: RunContext, selected: list[SelectedAncestor], *, parent_depth: int) -> None:
        paper = ctx.require_paper()
        existing = {item.canonical_id: item for item in ctx.ancestors}
        for item in selected:
            depth = parent_depth + item.depth
            if depth > ctx.settings.ancestor_max_depth:
                continue
            introduced = list(item.scored.introduced_topic_ids)
            names = [topic.name for topic in ctx.topics if topic.id in introduced]
            blurb = paper_blurb(
                title=item.scored.candidate.title,
                role=item.scored.role,
                topic_names=names,
                target_title=paper.title,
            )
            current = existing.get(item.canonical_id)
            if current is None:
                current = AncestorPaper(
                    canonical_id=item.canonical_id,
                    arxiv_id=item.scored.candidate.arxiv_id,
                    title=item.scored.candidate.title,
                    year=item.scored.candidate.year,
                    abstract=item.scored.candidate.abstract,
                    url=item.scored.candidate.url,
                    role=item.scored.role,
                    reading_minutes=item.scored.reading_minutes,
                    priority=item.priority,
                    depth=depth,
                    path_count=item.path_count,
                    why_it_matters=blurb,
                )
                ctx.ancestors.append(current)
                existing[current.canonical_id] = current
            else:
                current.path_count += item.path_count
                current.priority = max(current.priority, item.priority)
                current.depth = min(current.depth, depth)

            parent_ids = item.via or [paper.work_id]
            for parent_id in parent_ids:
                ctx.links.append(
                    PaperLink(
                        from_paper=parent_id,
                        to_paper=item.canonical_id,
                        citation_contexts=[context.text for context in item.scored.candidate.contexts],
                        sections=[context.section.value for context in item.scored.candidate.contexts],
                        influential=item.scored.candidate.influential,
                        builds_on_confidence=item.scored.builds_on_confidence,
                    )
                )
            for topic_id in introduced:
                ctx.paper_topics.append(
                    PaperTopic(
                        paper_id=item.canonical_id,
                        topic_id=topic_id,
                        relation=Relation.INTRODUCED,
                        confidence=item.scored.builds_on_confidence,
                    )
                )
            if item.scored.builds_on:
                mentioned = _mentioned_topics(item.scored.candidate, ctx)
                for topic_id in mentioned:
                    if topic_id in introduced:
                        continue
                    ctx.paper_topics.append(
                        PaperTopic(
                            paper_id=item.canonical_id,
                            topic_id=topic_id,
                            relation=Relation.DEVELOPS,
                            confidence=item.scored.builds_on_confidence,
                        )
                    )
        _dedupe(ctx)


def candidate_to_dict(candidate: Candidate) -> dict:
    return {
        "canonical_id": candidate.canonical_id,
        "title": candidate.title,
        "year": candidate.year,
        "arxiv_id": candidate.arxiv_id,
        "abstract": candidate.abstract,
        "url": candidate.url,
        "influential": candidate.influential,
        "page_count": candidate.page_count,
        "contexts": [{"section": item.section.value, "text": item.text} for item in candidate.contexts],
    }


def candidate_from_dict(payload: dict) -> Candidate:
    contexts = tuple(
        CitationContext(section=CitationSection(item["section"]), text=item["text"])
        for item in payload.get("contexts") or []
    )
    return Candidate(
        canonical_id=payload["canonical_id"],
        title=payload["title"],
        year=payload.get("year"),
        arxiv_id=payload.get("arxiv_id"),
        abstract=payload.get("abstract") or "",
        url=payload.get("url"),
        influential=bool(payload.get("influential")),
        contexts=contexts,
        page_count=payload.get("page_count"),
    )


def scored_from_cache(candidate: Candidate, scores: dict) -> ScoredCandidate:
    role = _role_value(scores.get("role"))
    usefulness = int(scores.get("learner_usefulness") or 3)
    introduced = tuple(scores.get("introduced_topic_ids") or [])
    builds_on = bool(scores.get("builds_on"))
    confidence = float(scores.get("builds_on_confidence") or 0)
    reading = int(scores.get("reading_minutes") or estimate_reading_minutes(candidate.page_count, usefulness))
    priority = compute_priority(
        contexts=candidate.contexts,
        influential=candidate.influential,
        builds_on=builds_on,
        builds_on_confidence=confidence,
        introduced_count=len(introduced),
        role=role,
        learner_usefulness=usefulness,
        path_count=1,
    )
    return ScoredCandidate(
        candidate=candidate,
        builds_on=builds_on,
        builds_on_confidence=confidence,
        introduced_topic_ids=introduced,
        role=role,
        learner_usefulness=usefulness,
        reading_minutes=reading,
        base_priority=priority,
    )


def _budget(ctx: RunContext) -> Budget:
    return Budget(
        max_papers=ctx.settings.ancestor_paper_budget,
        max_reading_minutes=ctx.settings.ancestor_reading_minutes,
        max_depth=ctx.settings.ancestor_max_depth,
    )


def _topic_hash(ctx: RunContext) -> str:
    raw = json.dumps([topic.id for topic in ctx.topics], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _role(answer: object) -> PaperRole:
    if isinstance(answer, ChoiceAnswer):
        return _role_value(answer.choice)
    return PaperRole.BACKGROUND


def _role_value(value: object) -> PaperRole:
    try:
        return PaperRole(str(value))
    except ValueError:
        return PaperRole.BACKGROUND


def _dedupe(ctx: RunContext) -> None:
    links: list[PaperLink] = []
    seen_links: set[tuple[str, str]] = set()
    for link in ctx.links:
        key = (link.from_paper, link.to_paper)
        if key in seen_links:
            continue
        seen_links.add(key)
        links.append(link)
    ctx.links = links
    topics: list[PaperTopic] = []
    seen_topics: set[tuple[str, str, str]] = set()
    for item in ctx.paper_topics:
        key = (item.paper_id, item.topic_id, item.relation.value)
        if key in seen_topics:
            continue
        seen_topics.add(key)
        topics.append(item)
    ctx.paper_topics = topics


def _mentioned_topics(candidate: Candidate, ctx: RunContext) -> list[str]:
    haystack = " ".join(
        [candidate.title, candidate.abstract, *(item.text for item in candidate.contexts)]
    ).lower()
    return [topic.id for topic in ctx.topics if topic.name.lower() in haystack]
