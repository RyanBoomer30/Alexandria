"""Shared state for one generation run."""

from dataclasses import dataclass, field

from paperpath.clients.arxiv import ArxivClient
from paperpath.clients.frontier import FrontierClient
from paperpath.clients.jev import JudgmentClient, UnavailablePdfExtractor
from paperpath.clients.openalex import OpenAlexClient
from paperpath.clients.semantic_scholar import SemanticScholarClient
from paperpath.clients.wikipedia import WikipediaClient
from paperpath.config import Settings
from paperpath.db.repository import Store
from paperpath.domain.arxiv import ArxivId
from paperpath.domain.models import (
    AncestorPaper,
    Edge,
    Paper,
    PaperLink,
    PaperTopic,
    Resource,
    Section,
    Topic,
)


@dataclass
class Clients:
    arxiv: ArxivClient
    scholar: SemanticScholarClient
    openalex: OpenAlexClient
    wikipedia: WikipediaClient
    frontier: FrontierClient
    judgments: JudgmentClient
    pdf: UnavailablePdfExtractor


@dataclass
class RunContext:
    settings: Settings
    store: Store
    clients: Clients
    job_id: str
    arxiv_id: ArxivId
    paper: Paper | None = None
    sections: list[Section] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    ancestors: list[AncestorPaper] = field(default_factory=list)
    links: list[PaperLink] = field(default_factory=list)
    paper_topics: list[PaperTopic] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)

    def require_paper(self) -> Paper:
        if self.paper is None:
            raise RuntimeError("Ingestion has not produced a paper yet.")
        return self.paper
