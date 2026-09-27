"""SQLite tables for the cached roadmap, per-user view, and call log."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now().astimezone()


class PaperRow(Base):
    __tablename__ = "papers"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    arxiv_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    authors: Mapped[list] = mapped_column(JSON, default=list)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    source_type: Mapped[str] = mapped_column(String, default="metadata_only")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    text_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class RoadmapRow(Base):
    __tablename__ = "roadmaps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    paper_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, index=True, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TopicRow(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("paper_key", "topic_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_key: Mapped[str] = mapped_column(ForeignKey("papers.key"), index=True)
    topic_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    usage_description: Mapped[str] = mapped_column(Text, default="")
    locations: Mapped[list] = mapped_column(JSON, default=list)
    related_references: Mapped[list] = mapped_column(JSON, default=list)
    essentiality: Mapped[str] = mapped_column(String)
    difficulty: Mapped[int] = mapped_column(Integer)
    why_it_matters: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    origin: Mapped[str] = mapped_column(String, default="extracted")


class EdgeRow(Base):
    __tablename__ = "edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_key: Mapped[str] = mapped_column(ForeignKey("papers.key"), index=True)
    from_topic: Mapped[str] = mapped_column(String)
    to_topic: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String)
    kept: Mapped[bool] = mapped_column(Boolean, default=False)
    drop_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class AncestorRow(Base):
    __tablename__ = "ancestor_papers"
    __table_args__ = (UniqueConstraint("roadmap_paper_key", "canonical_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    roadmap_paper_key: Mapped[str] = mapped_column(String, index=True)
    canonical_id: Mapped[str] = mapped_column(String)
    arxiv_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    abstract: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String)
    reading_time_estimate: Mapped[int] = mapped_column(Integer, default=30)
    priority: Mapped[float] = mapped_column(Float, default=0)
    depth: Mapped[int] = mapped_column(Integer, default=1)
    path_count: Mapped[int] = mapped_column(Integer, default=1)
    expanded: Mapped[bool] = mapped_column(Boolean, default=False)
    why_it_matters: Mapped[str] = mapped_column(Text, default="")


class PaperLinkRow(Base):
    __tablename__ = "paper_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    roadmap_paper_key: Mapped[str] = mapped_column(String, index=True)
    from_paper: Mapped[str] = mapped_column(String)
    to_paper: Mapped[str] = mapped_column(String)
    citation_contexts: Mapped[list] = mapped_column(JSON, default=list)
    sections: Mapped[list] = mapped_column(JSON, default=list)
    influential: Mapped[bool] = mapped_column(Boolean, default=False)
    builds_on_confidence: Mapped[float] = mapped_column(Float, default=0)


class PaperTopicRow(Base):
    __tablename__ = "paper_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    roadmap_paper_key: Mapped[str] = mapped_column(String, index=True)
    paper_id: Mapped[str] = mapped_column(String)
    topic_id: Mapped[str] = mapped_column(String)
    relation: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)


class ResourceRow(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_key: Mapped[str] = mapped_column(String, index=True)
    topic_id: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserRoadmapRow(Base):
    __tablename__ = "user_roadmaps"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    paper_key: Mapped[str] = mapped_column(String, primary_key=True)
    pruned_topics: Mapped[list] = mapped_column(JSON, default=list)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)


class CallLogRow(Base):
    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    roadmap_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    stage: Mapped[str] = mapped_column(String, index=True)
    model: Mapped[str] = mapped_column(String)
    prefix_hash: Mapped[str] = mapped_column(String)
    prompt_hash: Mapped[str] = mapped_column(String, index=True)
    inputs: Mapped[dict] = mapped_column(JSON)
    outputs: Mapped[dict] = mapped_column(JSON)
    latency_ms: Mapped[float] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReferenceCacheRow(Base):
    """Reference lists cached globally by canonical paper id, shared across roadmaps."""

    __tablename__ = "reference_cache"

    canonical_id: Mapped[str] = mapped_column(String, primary_key=True)
    references: Mapped[list] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class JudgmentCacheRow(Base):
    """Jev scores for a (target, candidate) pair, shared across roadmaps."""

    __tablename__ = "judgment_cache"

    target_id: Mapped[str] = mapped_column(String, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String, primary_key=True)
    scores: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
