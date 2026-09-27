"""Read and write the roadmap aggregate, user view, call log, and shared caches."""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from paperpath.db.models import (
    AncestorRow,
    CallLogRow,
    EdgeRow,
    JudgmentCacheRow,
    PaperLinkRow,
    PaperRow,
    PaperTopicRow,
    ReferenceCacheRow,
    ResourceRow,
    RoadmapRow,
    TopicRow,
    UserRoadmapRow,
)
from paperpath.domain.models import (
    AncestorPaper,
    CallLogEntry,
    Edge,
    EdgeSource,
    Essentiality,
    Paper,
    PaperLink,
    PaperRole,
    PaperTopic,
    Relation,
    Resource,
    ResourceType,
    Roadmap,
    SourceType,
    Topic,
    TopicOrigin,
    TopicStatus,
    UserRoadmap,
)
from paperpath.errors import NotFoundError


class Store:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def upsert_paper(self, paper: Paper) -> None:
        with self._sessions() as session:
            row = session.get(PaperRow, paper.key)
            if row is None:
                row = PaperRow(key=paper.key, arxiv_id=paper.arxiv_id)
                session.add(row)
            row.arxiv_id = paper.arxiv_id
            row.version = paper.version
            row.title = paper.title
            row.abstract = paper.abstract
            row.authors = paper.authors
            row.categories = paper.categories
            row.source_type = paper.source_type.value
            row.fetched_at = paper.fetched_at
            row.published = paper.published
            row.text_path = paper.text_path
            session.commit()

    def get_paper(self, key: str) -> Paper | None:
        with self._sessions() as session:
            row = session.get(PaperRow, key)
            return _paper(row) if row else None

    def create_roadmap(self, roadmap_id: str, paper_key: str) -> str:
        with self._sessions() as session:
            existing = session.scalar(select(RoadmapRow).where(RoadmapRow.paper_key == paper_key))
            if existing is not None:
                if existing.status == "failed":
                    existing.status = "pending"
                    existing.error = None
                    existing.updated_at = _now()
                    session.commit()
                return existing.id
            session.add(
                RoadmapRow(
                    id=roadmap_id,
                    paper_key=paper_key,
                    status="pending",
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(select(RoadmapRow).where(RoadmapRow.paper_key == paper_key))
                if existing is None:
                    raise
                return existing.id
            return roadmap_id

    def get_job(self, roadmap_id: str) -> tuple[str, str, str | None] | None:
        """Return (paper_key, status, error) for a roadmap id."""
        with self._sessions() as session:
            row = session.get(RoadmapRow, roadmap_id)
            if row is None:
                return None
            return row.paper_key, row.status, row.error

    def get_job_by_paper(self, paper_key: str) -> tuple[str, str, str | None] | None:
        """Return (roadmap_id, status, error) for a paper key."""
        with self._sessions() as session:
            row = session.scalar(select(RoadmapRow).where(RoadmapRow.paper_key == paper_key))
            if row is None:
                return None
            return row.id, row.status, row.error

    def align_job(self, roadmap_id: str, paper_key: str) -> None:
        with self._sessions() as session:
            row = session.get(RoadmapRow, roadmap_id)
            if row is None or row.paper_key == paper_key:
                return
            row.paper_key = paper_key
            row.updated_at = _now()
            session.commit()

    def set_status(self, roadmap_id: str, status: str, error: str | None = None) -> None:
        with self._sessions() as session:
            row = session.get(RoadmapRow, roadmap_id)
            if row is None:
                return
            row.status = status
            row.error = error
            row.updated_at = _now()
            session.commit()

    def save_roadmap(self, roadmap: Roadmap) -> None:
        self.upsert_paper(roadmap.paper)
        with self._sessions() as session:
            paper_key = roadmap.paper.key
            for model, column in (
                (TopicRow, TopicRow.paper_key),
                (EdgeRow, EdgeRow.paper_key),
                (AncestorRow, AncestorRow.roadmap_paper_key),
                (PaperLinkRow, PaperLinkRow.roadmap_paper_key),
                (PaperTopicRow, PaperTopicRow.roadmap_paper_key),
                (ResourceRow, ResourceRow.paper_key),
            ):
                session.execute(delete(model).where(column == paper_key))
            session.add_all(_topic_rows(paper_key, roadmap.topics))
            session.add_all(_edge_rows(paper_key, roadmap.edges))
            session.add_all(_ancestor_rows(paper_key, roadmap.ancestors))
            session.add_all(_link_rows(paper_key, roadmap.links))
            session.add_all(_paper_topic_rows(paper_key, roadmap.paper_topics))
            session.add_all(_resource_rows(paper_key, roadmap.resources))
            job = session.get(RoadmapRow, roadmap.id)
            if job is not None:
                job.status = "ready"
                job.error = None
                job.updated_at = _now()
            session.commit()

    def load_roadmap(self, roadmap_id: str) -> Roadmap:
        with self._sessions() as session:
            job = session.get(RoadmapRow, roadmap_id)
            if job is None:
                raise NotFoundError(f"No roadmap {roadmap_id}.")
            return self._load_key(session, job.id, job.paper_key)

    def load_roadmap_by_paper(self, paper_key: str) -> Roadmap | None:
        with self._sessions() as session:
            job = session.scalar(select(RoadmapRow).where(RoadmapRow.paper_key == paper_key))
            if job is None or job.status != "ready":
                return None
            return self._load_key(session, job.id, paper_key)

    def _load_key(self, session: Session, roadmap_id: str, paper_key: str) -> Roadmap:
        paper_row = session.get(PaperRow, paper_key)
        if paper_row is None:
            raise NotFoundError(f"No paper stored for {paper_key}.")
        topics = session.scalars(select(TopicRow).where(TopicRow.paper_key == paper_key)).all()
        edges = session.scalars(select(EdgeRow).where(EdgeRow.paper_key == paper_key)).all()
        ancestors = session.scalars(
            select(AncestorRow).where(AncestorRow.roadmap_paper_key == paper_key)
        ).all()
        links = session.scalars(
            select(PaperLinkRow).where(PaperLinkRow.roadmap_paper_key == paper_key)
        ).all()
        paper_topics = session.scalars(
            select(PaperTopicRow).where(PaperTopicRow.roadmap_paper_key == paper_key)
        ).all()
        resources = session.scalars(select(ResourceRow).where(ResourceRow.paper_key == paper_key)).all()
        return Roadmap(
            id=roadmap_id,
            paper=_paper(paper_row),
            topics=[_topic(row) for row in topics],
            edges=[_edge(row) for row in edges],
            ancestors=[_ancestor(row) for row in ancestors],
            links=[_link(row) for row in links],
            paper_topics=[_paper_topic(row) for row in paper_topics],
            resources=[_resource(row) for row in resources],
        )

    def get_user(self, user_id: str, paper_key: str) -> UserRoadmap:
        with self._sessions() as session:
            row = session.get(UserRoadmapRow, (user_id, paper_key))
            if row is None:
                return UserRoadmap(user_id=user_id, paper_key=paper_key)
            return UserRoadmap(
                user_id=row.user_id,
                paper_key=row.paper_key,
                pruned_topics=list(row.pruned_topics or []),
                progress={key: TopicStatus(value) for key, value in (row.progress or {}).items()},
            )

    def save_user(self, user: UserRoadmap) -> None:
        with self._sessions() as session:
            row = session.get(UserRoadmapRow, (user.user_id, user.paper_key))
            if row is None:
                row = UserRoadmapRow(user_id=user.user_id, paper_key=user.paper_key)
                session.add(row)
            row.pruned_topics = user.pruned_topics
            row.progress = {key: value.value for key, value in user.progress.items()}
            session.commit()

    def record_call(self, entry: CallLogEntry) -> None:
        with self._sessions() as session:
            session.add(
                CallLogRow(
                    roadmap_id=entry.roadmap_id,
                    stage=entry.stage,
                    model=entry.model,
                    prefix_hash=entry.prefix_hash,
                    prompt_hash=entry.prompt_hash,
                    inputs=entry.inputs,
                    outputs=entry.outputs,
                    latency_ms=entry.latency_ms,
                    cost=entry.cost,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    created_at=_now(),
                )
            )
            session.commit()

    def cost_summary(self, roadmap_id: str) -> dict[str, float]:
        with self._sessions() as session:
            rows = session.execute(
                select(CallLogRow.model, func.coalesce(func.sum(CallLogRow.cost), 0.0))
                .where(CallLogRow.roadmap_id == roadmap_id)
                .group_by(CallLogRow.model)
            ).all()
            return {model: float(cost) for model, cost in rows}

    def get_references(self, canonical_id: str) -> list[dict] | None:
        with self._sessions() as session:
            row = session.get(ReferenceCacheRow, canonical_id)
            return list(row.references) if row else None

    def put_references(self, canonical_id: str, references: list[dict]) -> None:
        with self._sessions() as session:
            row = session.get(ReferenceCacheRow, canonical_id)
            if row is None:
                row = ReferenceCacheRow(canonical_id=canonical_id, references=references, fetched_at=_now())
                session.add(row)
            else:
                row.references = references
                row.fetched_at = _now()
            session.commit()

    def get_judgment(self, target_id: str, candidate_id: str) -> dict | None:
        with self._sessions() as session:
            row = session.get(JudgmentCacheRow, (target_id, candidate_id))
            return dict(row.scores) if row else None

    def put_judgment(self, target_id: str, candidate_id: str, scores: dict, model: str) -> None:
        with self._sessions() as session:
            row = session.get(JudgmentCacheRow, (target_id, candidate_id))
            if row is None:
                session.add(
                    JudgmentCacheRow(
                        target_id=target_id,
                        candidate_id=candidate_id,
                        scores=scores,
                        model=model,
                        created_at=_now(),
                    )
                )
            else:
                row.scores = scores
                row.model = model
                row.created_at = _now()
            session.commit()


def _now() -> datetime:
    return datetime.now().astimezone()


def _paper(row: PaperRow) -> Paper:
    return Paper(
        key=row.key,
        arxiv_id=row.arxiv_id,
        version=row.version,
        title=row.title,
        abstract=row.abstract,
        authors=list(row.authors or []),
        categories=list(row.categories or []),
        source_type=SourceType(row.source_type),
        fetched_at=row.fetched_at,
        published=row.published,
        text_path=row.text_path,
    )


def _topic(row: TopicRow) -> Topic:
    return Topic(
        id=row.topic_id,
        name=row.name,
        aliases=list(row.aliases or []),
        usage_description=row.usage_description,
        locations=list(row.locations or []),
        related_references=list(row.related_references or []),
        essentiality=Essentiality(row.essentiality),
        difficulty=row.difficulty,
        why_it_matters=row.why_it_matters,
        position=row.position,
        level=row.level,
        included=row.included,
        origin=TopicOrigin(row.origin),
    )


def _edge(row: EdgeRow) -> Edge:
    return Edge(
        prerequisite_id=row.from_topic,
        dependent_id=row.to_topic,
        confidence=row.confidence,
        source=EdgeSource(row.source),
        kept=row.kept,
        drop_reason=row.drop_reason,
    )


def _ancestor(row: AncestorRow) -> AncestorPaper:
    return AncestorPaper(
        canonical_id=row.canonical_id,
        arxiv_id=row.arxiv_id,
        title=row.title,
        year=row.year,
        abstract=row.abstract,
        url=row.url,
        role=PaperRole(row.role),
        reading_minutes=row.reading_time_estimate,
        priority=row.priority,
        depth=row.depth,
        path_count=row.path_count,
        expanded=row.expanded,
        why_it_matters=row.why_it_matters,
    )


def _link(row: PaperLinkRow) -> PaperLink:
    return PaperLink(
        from_paper=row.from_paper,
        to_paper=row.to_paper,
        citation_contexts=list(row.citation_contexts or []),
        sections=list(row.sections or []),
        influential=row.influential,
        builds_on_confidence=row.builds_on_confidence,
    )


def _paper_topic(row: PaperTopicRow) -> PaperTopic:
    return PaperTopic(
        paper_id=row.paper_id,
        topic_id=row.topic_id,
        relation=Relation(row.relation),
        confidence=row.confidence,
    )


def _resource(row: ResourceRow) -> Resource:
    return Resource(
        topic_id=row.topic_id,
        type=ResourceType(row.type),
        url=row.url,
        title=row.title,
        verified=row.verified,
        match_confidence=row.match_confidence,
        excerpt=row.excerpt,
        attribution=row.attribution,
    )


def _topic_rows(paper_key: str, topics: list[Topic]) -> list[TopicRow]:
    return [
        TopicRow(
            paper_key=paper_key,
            topic_id=topic.id,
            name=topic.name,
            aliases=topic.aliases,
            usage_description=topic.usage_description,
            locations=topic.locations,
            related_references=topic.related_references,
            essentiality=topic.essentiality.value,
            difficulty=topic.difficulty,
            why_it_matters=topic.why_it_matters,
            position=topic.position,
            level=topic.level,
            included=topic.included,
            origin=topic.origin.value,
        )
        for topic in topics
    ]


def _edge_rows(paper_key: str, edges: list[Edge]) -> list[EdgeRow]:
    return [
        EdgeRow(
            paper_key=paper_key,
            from_topic=edge.prerequisite_id,
            to_topic=edge.dependent_id,
            confidence=edge.confidence,
            source=edge.source.value,
            kept=edge.kept,
            drop_reason=edge.drop_reason,
        )
        for edge in edges
    ]


def _ancestor_rows(paper_key: str, ancestors: list[AncestorPaper]) -> list[AncestorRow]:
    return [
        AncestorRow(
            roadmap_paper_key=paper_key,
            canonical_id=item.canonical_id,
            arxiv_id=item.arxiv_id,
            title=item.title,
            year=item.year,
            abstract=item.abstract,
            url=item.url,
            role=item.role.value,
            reading_time_estimate=item.reading_minutes,
            priority=item.priority,
            depth=item.depth,
            path_count=item.path_count,
            expanded=item.expanded,
            why_it_matters=item.why_it_matters,
        )
        for item in ancestors
    ]


def _link_rows(paper_key: str, links: list[PaperLink]) -> list[PaperLinkRow]:
    return [
        PaperLinkRow(
            roadmap_paper_key=paper_key,
            from_paper=link.from_paper,
            to_paper=link.to_paper,
            citation_contexts=link.citation_contexts,
            sections=link.sections,
            influential=link.influential,
            builds_on_confidence=link.builds_on_confidence,
        )
        for link in links
    ]


def _paper_topic_rows(paper_key: str, rows: list[PaperTopic]) -> list[PaperTopicRow]:
    return [
        PaperTopicRow(
            roadmap_paper_key=paper_key,
            paper_id=item.paper_id,
            topic_id=item.topic_id,
            relation=item.relation.value,
            confidence=item.confidence,
        )
        for item in rows
    ]


def _resource_rows(paper_key: str, resources: list[Resource]) -> list[ResourceRow]:
    return [
        ResourceRow(
            paper_key=paper_key,
            topic_id=item.topic_id,
            type=item.type.value,
            url=item.url,
            title=item.title,
            verified=item.verified,
            match_confidence=item.match_confidence,
            excerpt=item.excerpt,
            attribution=item.attribution,
        )
        for item in resources
    ]


