"""Wire the default clients and stages."""

from dataclasses import dataclass

import httpx

from paperpath.clients.arxiv import ArxivClient
from paperpath.clients.frontier import FrontierClient
from paperpath.clients.jev import JevClient, JudgmentClient, UnavailablePdfExtractor
from paperpath.clients.openalex import OpenAlexClient
from paperpath.clients.semantic_scholar import SemanticScholarClient
from paperpath.clients.wikipedia import WikipediaClient
from paperpath.config import Settings
from paperpath.db import create_all, make_engine, make_session_factory
from paperpath.db.repository import Store
from paperpath.pipeline.context import Clients
from paperpath.pipeline.jobs import JobHub
from paperpath.pipeline.runner import Pipeline
from paperpath.pipeline.stages.ancestors import AncestorStage
from paperpath.pipeline.stages.graph import GraphStage
from paperpath.pipeline.stages.ingestion import IngestionStage
from paperpath.pipeline.stages.judgments import EdgeVerificationStage, JudgmentStage
from paperpath.pipeline.stages.language import EdgeProposalStage, ExplanationStage, TopicExtractionStage
from paperpath.pipeline.stages.resources import ResourceStage


def default_stages() -> list:
    return [
        IngestionStage(),
        TopicExtractionStage(),
        JudgmentStage(),
        EdgeProposalStage(),
        EdgeVerificationStage(),
        GraphStage(),
        AncestorStage(),
        ResourceStage(),
        ExplanationStage(),
    ]


@dataclass
class Runtime:
    settings: Settings
    store: Store
    jobs: JobHub
    http: httpx.AsyncClient
    pipeline: Pipeline


def build_runtime(settings: Settings | None = None, clients: Clients | None = None) -> Runtime:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    create_all(engine)
    store = Store(make_session_factory(engine))
    http = httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    )
    jobs = JobHub()
    if clients is None:
        clients = build_clients(settings, http, store)
    pipeline = Pipeline(default_stages(), store, jobs, settings, clients)
    return Runtime(settings=settings, store=store, jobs=jobs, http=http, pipeline=pipeline)


def build_clients(settings: Settings, http: httpx.AsyncClient, store: Store) -> Clients:
    recorder = store.record_call
    frontier = FrontierClient(
        http,
        base_url=settings.frontier_base_url,
        api_key=settings.frontier_api_key,
        model=settings.frontier_model,
        recorder=recorder,
    )
    jev = JevClient(
        http,
        base_url=settings.jev_base_url,
        api_key=settings.jev_api_key,
        model=settings.jev_model,
        yes_threshold=settings.noul_yes_threshold,
        app_name=settings.app_name,
        recorder=recorder,
    )
    return Clients(
        arxiv=ArxivClient(http, min_interval=settings.arxiv_min_interval_seconds, user_agent=settings.user_agent),
        scholar=SemanticScholarClient(http, api_key=settings.s2_api_key, min_interval=settings.s2_min_interval_seconds),
        openalex=OpenAlexClient(http, mailto=settings.openalex_mailto or settings.contact_email),
        wikipedia=WikipediaClient(http, user_agent=settings.user_agent),
        frontier=frontier,
        judgments=JudgmentClient(jev, frontier, settings),
        pdf=UnavailablePdfExtractor(),
    )
