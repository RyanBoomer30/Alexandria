"""HTTP routes over the pipeline."""

import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from paperpath.api.schemas import CreateRoadmap, JobResponse, PersonalizeRequest, ProgressRequest
from paperpath.domain.arxiv import parse_arxiv_id
from paperpath.domain.ordering import learning_path
from paperpath.domain.personalize import apply_progress, diagnostic_questions, prune_known, view_for_user
from paperpath.errors import IngestionError, NotFoundError, NotReadyError
from paperpath.export.vault import build_vault, zip_vault
from paperpath.pipeline.jobs import ProgressEvent
from paperpath.pipeline.wiring import Runtime

router = APIRouter(prefix="/v1")


def _runtime(request: Request) -> Runtime:
    return request.app.state.runtime


@router.post("/roadmaps", response_model=JobResponse)
async def create_roadmap(body: CreateRoadmap, request: Request) -> JobResponse:
    runtime = _runtime(request)
    arxiv_id = parse_arxiv_id(body.arxiv)
    if arxiv_id.version is None:
        paper = await runtime.pipeline.clients.arxiv.fetch_metadata(arxiv_id)
        if paper.version is None:
            raise IngestionError(f"arXiv did not report a version for {arxiv_id.base}.")
        arxiv_id = arxiv_id.with_version(paper.version)
        runtime.store.upsert_paper(paper)
    existing = runtime.store.get_job_by_paper(arxiv_id.canonical)
    if existing and existing[1] in {"ready", "running"}:
        roadmap_id, status, error = existing
        return JobResponse(id=roadmap_id, paper_key=arxiv_id.canonical, status=status, error=error)
    roadmap_id = runtime.store.create_roadmap(str(uuid.uuid4()), arxiv_id.canonical)
    if runtime.settings.inline_jobs:
        await runtime.pipeline.run(roadmap_id, arxiv_id)
    else:
        runtime.jobs.spawn(runtime.pipeline.run(roadmap_id, arxiv_id))
    job = runtime.store.get_job(roadmap_id)
    if job is None:
        raise NotFoundError(f"No roadmap {roadmap_id}.")
    return JobResponse(id=roadmap_id, paper_key=job[0], status=job[1], error=job[2])


@router.get("/roadmaps/{roadmap_id}")
async def get_roadmap(
    roadmap_id: str,
    request: Request,
    user_id: str | None = None,
    audit: bool = False,
) -> dict:
    runtime = _runtime(request)
    job = runtime.store.get_job(roadmap_id)
    if job is None:
        raise NotFoundError(f"No roadmap {roadmap_id}.")
    paper_key, status, error = job
    payload: dict = {"id": roadmap_id, "paper_key": paper_key, "status": status, "error": error}
    if status != "ready":
        return payload
    roadmap = runtime.store.load_roadmap(roadmap_id)
    user = runtime.store.get_user(user_id, roadmap.paper.key) if user_id else None
    view = view_for_user(roadmap, user)
    edges = view.edges if audit else view.kept_edges()
    payload.update(
        {
            "paper": view.paper.model_dump(mode="json"),
            "topics": [_topic_payload(topic, user.progress if user else {}) for topic in view.included_topics()],
            "edges": [edge.model_dump(mode="json") for edge in edges],
            "ancestors": [item.model_dump(mode="json") for item in view.ancestors],
            "resources": [item.model_dump(mode="json") for item in view.resources],
            "path": [item.model_dump(mode="json") for item in learning_path(view)],
        }
    )
    return payload


@router.get("/roadmaps/{roadmap_id}/events")
async def roadmap_events(roadmap_id: str, request: Request) -> StreamingResponse:
    runtime = _runtime(request)
    job = runtime.store.get_job(roadmap_id)
    if job is None:
        raise NotFoundError(f"No roadmap {roadmap_id}.")

    async def stream():
        status = job[1]
        if status in {"ready", "failed"}:
            event = ProgressEvent(
                stage="pipeline",
                status="finished" if status == "ready" else "failed",
                detail=job[2] or "",
            )
            yield _sse(event)
            return
        queue = runtime.jobs.subscribe(roadmap_id)
        while True:
            if await request.is_disconnected():
                break
            event = await queue.get()
            yield _sse(event)
            if event.stage == "pipeline" and event.status in {"finished", "failed"}:
                break

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/roadmaps/{roadmap_id}/diagnostic")
async def diagnostic(roadmap_id: str, request: Request) -> dict:
    runtime = _runtime(request)
    roadmap = runtime.pipeline.require_ready(roadmap_id)
    questions = diagnostic_questions(roadmap, runtime.settings.diagnostic_questions)
    return {"questions": [item.model_dump(mode="json") for item in questions]}


@router.post("/roadmaps/{roadmap_id}/personalize")
async def personalize(roadmap_id: str, body: PersonalizeRequest, request: Request) -> dict:
    runtime = _runtime(request)
    roadmap = runtime.pipeline.require_ready(roadmap_id)
    known = list(body.known_topic_ids)
    if body.answers:
        known.extend(
            await runtime.pipeline.score_known(
                roadmap_id,
                [(item.topic_id, item.question, item.answer) for item in body.answers],
            )
        )
    user = runtime.store.get_user(body.user_id, roadmap.paper.key)
    user = prune_known(user, known)
    runtime.store.save_user(user)
    return {"user_id": body.user_id, "pruned_topics": user.pruned_topics}


@router.post("/roadmaps/{roadmap_id}/progress")
async def update_progress(roadmap_id: str, body: ProgressRequest, request: Request) -> dict:
    runtime = _runtime(request)
    roadmap = runtime.pipeline.require_ready(roadmap_id)
    known_paper = any(item.canonical_id == body.topic_id for item in roadmap.ancestors)
    if roadmap.topic(body.topic_id) is None and not known_paper:
        raise NotFoundError(f"Roadmap {roadmap_id} has no topic or paper {body.topic_id}.")
    user = runtime.store.get_user(body.user_id, roadmap.paper.key)
    user = apply_progress(user, body.topic_id, body.status)
    runtime.store.save_user(user)
    return {"user_id": body.user_id, "progress": {key: value.value for key, value in user.progress.items()}}


@router.post("/roadmaps/{roadmap_id}/expand")
async def expand_ancestor(roadmap_id: str, canonical_id: str, request: Request) -> dict:
    roadmap = await _runtime(request).pipeline.expand_ancestor(roadmap_id, canonical_id)
    return {
        "id": roadmap.id,
        "ancestors": [item.model_dump(mode="json") for item in roadmap.ancestors],
    }


@router.get("/roadmaps/{roadmap_id}/export")
async def export_vault(
    roadmap_id: str,
    request: Request,
    user_id: str | None = None,
) -> Response:
    runtime = _runtime(request)
    job = runtime.store.get_job(roadmap_id)
    if job is None:
        raise NotFoundError(f"No roadmap {roadmap_id}.")
    if job[1] != "ready":
        raise NotReadyError(f"Roadmap {roadmap_id} is {job[1]}.")
    roadmap = runtime.store.load_roadmap(roadmap_id)
    user = runtime.store.get_user(user_id, roadmap.paper.key) if user_id else None
    view = view_for_user(roadmap, user)
    payload = zip_vault(build_vault(view, user))
    filename = f"paperpath-{roadmap.paper.key.replace('/', '_')}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/roadmaps/{roadmap_id}/costs")
async def costs(roadmap_id: str, request: Request) -> dict:
    runtime = _runtime(request)
    if runtime.store.get_job(roadmap_id) is None:
        raise NotFoundError(f"No roadmap {roadmap_id}.")
    summary = runtime.store.cost_summary(roadmap_id)
    return {"roadmap_id": roadmap_id, "by_model": summary, "total": sum(summary.values())}


def _topic_payload(topic, progress: dict) -> dict:
    payload = topic.model_dump(mode="json")
    status = progress.get(topic.id)
    payload["status"] = status.value if status else "not_started"
    return payload


def _sse(event: ProgressEvent) -> str:
    return f"event: progress\ndata: {json.dumps(event.as_dict())}\n\n"
