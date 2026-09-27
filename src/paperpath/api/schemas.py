"""HTTP bodies. The cached roadmap is the full graph; a user id narrows the view."""

from pydantic import BaseModel, Field

from paperpath.domain.models import TopicStatus


class CreateRoadmap(BaseModel):
    arxiv: str


class JobResponse(BaseModel):
    id: str
    paper_key: str
    status: str
    error: str | None = None


class DiagnosticAnswer(BaseModel):
    topic_id: str
    question: str = ""
    answer: str


class PersonalizeRequest(BaseModel):
    user_id: str = "local"
    known_topic_ids: list[str] = Field(default_factory=list)
    answers: list[DiagnosticAnswer] = Field(default_factory=list)


class ProgressRequest(BaseModel):
    user_id: str = "local"
    topic_id: str
    status: TopicStatus
