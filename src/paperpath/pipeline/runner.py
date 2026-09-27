"""Run the generation stages in order and persist the unpersonalized roadmap."""

import asyncio
import logging

from paperpath.domain.arxiv import ArxivId
from paperpath.domain.models import Roadmap
from paperpath.errors import NotFoundError, NotReadyError
from paperpath.observability import current_roadmap_id
from paperpath.pipeline.context import Clients, RunContext
from paperpath.pipeline.jobs import JobHub, ProgressEvent
from paperpath.pipeline.stages.ancestors import AncestorStage
from paperpath.pipeline.stages.judgments import topics_the_reader_knows

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, stages: list, store, jobs: JobHub, settings, clients: Clients) -> None:
        self.stages = stages
        self.store = store
        self.jobs = jobs
        self.settings = settings
        self.clients = clients
        self._locks: dict[str, asyncio.Lock] = {}

    async def run(self, job_id: str, arxiv_id: ArxivId) -> None:
        lock = self._locks.setdefault(arxiv_id.base, asyncio.Lock())
        async with lock:
            token = current_roadmap_id.set(job_id)
            try:
                await self._run(job_id, arxiv_id)
            except Exception as exc:
                logger.exception("Roadmap %s failed", job_id)
                self.store.set_status(job_id, "failed", str(exc))
                self.jobs.emit(job_id, ProgressEvent(stage="pipeline", status="failed", detail=str(exc)))
            finally:
                current_roadmap_id.reset(token)

    async def _run(self, job_id: str, arxiv_id: ArxivId) -> None:
        job = self.store.get_job(job_id)
        if job and job[1] == "ready":
            self.jobs.emit(job_id, ProgressEvent(stage="pipeline", status="finished", detail="cached"))
            return
        self.store.set_status(job_id, "running")
        ctx = RunContext(
            settings=self.settings,
            store=self.store,
            clients=self.clients,
            job_id=job_id,
            arxiv_id=arxiv_id,
        )
        for stage in self.stages:
            self.jobs.emit(job_id, ProgressEvent(stage=stage.name, status="started"))
            await stage.run(ctx)
            self.jobs.emit(job_id, ProgressEvent(stage=stage.name, status="finished"))
        paper = ctx.require_paper()
        self.store.align_job(job_id, paper.key)
        self.store.save_roadmap(
            Roadmap(
                id=job_id,
                paper=paper,
                topics=ctx.topics,
                edges=ctx.edges,
                ancestors=ctx.ancestors,
                links=ctx.links,
                paper_topics=ctx.paper_topics,
                resources=ctx.resources,
            )
        )
        self.jobs.emit(job_id, ProgressEvent(stage="pipeline", status="finished"))

    async def expand_ancestor(self, roadmap_id: str, canonical_id: str) -> Roadmap:
        self.require_ready(roadmap_id)
        roadmap = self.store.load_roadmap(roadmap_id)
        if not any(item.canonical_id == canonical_id for item in roadmap.ancestors):
            raise NotFoundError(f"Roadmap {roadmap_id} has no paper {canonical_id}.")
        ctx = self._context_from(roadmap)
        token = current_roadmap_id.set(roadmap_id)
        try:
            await self._ancestors().expand_one(ctx, canonical_id)
        finally:
            current_roadmap_id.reset(token)
        updated = self._roadmap_from(ctx)
        self.store.save_roadmap(updated)
        return updated

    async def score_known(self, roadmap_id: str, answers: list[tuple[str, str, str]]) -> list[str]:
        roadmap = self.require_ready(roadmap_id)
        ctx = self._context_from(roadmap)
        token = current_roadmap_id.set(roadmap_id)
        try:
            return await topics_the_reader_knows(ctx, answers)
        finally:
            current_roadmap_id.reset(token)

    def require_ready(self, roadmap_id: str) -> Roadmap:
        job = self.store.get_job(roadmap_id)
        if job is None:
            raise NotFoundError(f"No roadmap {roadmap_id}.")
        if job[1] != "ready":
            raise NotReadyError(f"Roadmap {roadmap_id} is {job[1]}.")
        return self.store.load_roadmap(roadmap_id)

    def _ancestors(self) -> AncestorStage:
        for stage in self.stages:
            if isinstance(stage, AncestorStage):
                return stage
        raise RuntimeError("The pipeline has no ancestor stage.")

    def _context_from(self, roadmap: Roadmap) -> RunContext:
        from paperpath.domain.arxiv import parse_arxiv_id

        return RunContext(
            settings=self.settings,
            store=self.store,
            clients=self.clients,
            job_id=roadmap.id,
            arxiv_id=parse_arxiv_id(roadmap.paper.key),
            paper=roadmap.paper,
            topics=list(roadmap.topics),
            edges=list(roadmap.edges),
            ancestors=list(roadmap.ancestors),
            links=list(roadmap.links),
            paper_topics=list(roadmap.paper_topics),
            resources=list(roadmap.resources),
        )

    def _roadmap_from(self, ctx: RunContext) -> Roadmap:
        return Roadmap(
            id=ctx.job_id,
            paper=ctx.require_paper(),
            topics=ctx.topics,
            edges=ctx.edges,
            ancestors=ctx.ancestors,
            links=ctx.links,
            paper_topics=ctx.paper_topics,
            resources=ctx.resources,
        )
