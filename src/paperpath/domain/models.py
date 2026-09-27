"""Persisted entities. These match the core data model in the PRD."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    LATEX = "latex"
    HTML = "html"
    PDF = "pdf"
    METADATA_ONLY = "metadata_only"


class Essentiality(StrEnum):
    ESSENTIAL = "essential"
    SUPPORTING = "supporting"
    INCIDENTAL = "incidental"


class EdgeSource(StrEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"


class PaperRole(StrEnum):
    FOUNDATIONAL = "foundational_method"
    SURVEY = "survey_or_tutorial"
    BENCHMARK = "benchmark_or_dataset"
    BACKGROUND = "background"


class TopicStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TopicOrigin(StrEnum):
    EXTRACTED = "extracted"
    EXPANDED = "expanded"


class ResourceType(StrEnum):
    WIKIPEDIA = "wikipedia"
    PAPER = "paper"
    OTHER = "other"


class Relation(StrEnum):
    INTRODUCED = "introduced"
    DEVELOPS = "develops"


class Paper(BaseModel):
    key: str
    arxiv_id: str
    version: int | None = None
    title: str
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    source_type: SourceType = SourceType.METADATA_ONLY
    fetched_at: datetime | None = None
    published: datetime | None = None
    text_path: str | None = None

    @property
    def work_id(self) -> str:
        return f"arxiv:{self.arxiv_id.lower()}"


class Section(BaseModel):
    level: int
    title: str
    text: str


class Topic(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    usage_description: str = ""
    locations: list[str] = Field(default_factory=list)
    related_references: list[str] = Field(default_factory=list)
    essentiality: Essentiality = Essentiality.SUPPORTING
    difficulty: int = 3
    why_it_matters: str = ""
    position: int = 0
    level: int = 0
    included: bool = True
    origin: TopicOrigin = TopicOrigin.EXTRACTED


class Edge(BaseModel):
    prerequisite_id: str
    dependent_id: str
    confidence: float
    source: EdgeSource = EdgeSource.VERIFIED
    kept: bool = False
    drop_reason: str | None = None


class AncestorPaper(BaseModel):
    canonical_id: str
    arxiv_id: str | None = None
    title: str
    year: int | None = None
    abstract: str = ""
    url: str | None = None
    role: PaperRole = PaperRole.BACKGROUND
    reading_minutes: int = 30
    priority: float = 0.0
    depth: int = 1
    path_count: int = 1
    expanded: bool = False
    why_it_matters: str = ""


class PaperLink(BaseModel):
    from_paper: str
    to_paper: str
    citation_contexts: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    influential: bool = False
    builds_on_confidence: float = 0.0


class PaperTopic(BaseModel):
    paper_id: str
    topic_id: str
    relation: Relation
    confidence: float


class Resource(BaseModel):
    topic_id: str
    type: ResourceType
    url: str
    title: str
    verified: bool = False
    match_confidence: float | None = None
    excerpt: str | None = None
    attribution: str | None = None


class PathItem(BaseModel):
    kind: str
    id: str
    level: int


class Roadmap(BaseModel):
    id: str
    paper: Paper
    topics: list[Topic] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    ancestors: list[AncestorPaper] = Field(default_factory=list)
    links: list[PaperLink] = Field(default_factory=list)
    paper_topics: list[PaperTopic] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)

    def topic(self, topic_id: str) -> Topic | None:
        return next((item for item in self.topics if item.id == topic_id), None)

    def kept_edges(self) -> list[Edge]:
        return [edge for edge in self.edges if edge.kept]

    def included_topics(self) -> list[Topic]:
        topics = [topic for topic in self.topics if topic.included]
        return sorted(topics, key=lambda topic: (topic.position, topic.name))


class UserRoadmap(BaseModel):
    user_id: str
    paper_key: str
    pruned_topics: list[str] = Field(default_factory=list)
    progress: dict[str, TopicStatus] = Field(default_factory=dict)


class DiagnosticQuestion(BaseModel):
    topic_id: str
    topic_name: str
    prompt: str


class CallLogEntry(BaseModel):
    roadmap_id: str | None
    stage: str
    model: str
    prefix_hash: str
    prompt_hash: str
    inputs: dict
    outputs: dict
    latency_ms: float
    cost: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
