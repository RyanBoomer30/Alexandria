"""Command line: generate a roadmap, export a vault, or serve the API."""

import argparse
import asyncio
import logging

import uvicorn

from paperpath.app import create_app
from paperpath.config import Settings
from paperpath.domain.arxiv import parse_arxiv_id
from paperpath.domain.ordering import learning_path
from paperpath.export.vault import build_vault, zip_vault
from paperpath.pipeline.wiring import build_runtime


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="paperpath", description="Build a learning roadmap for an arXiv paper.")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Run the pipeline and print the learning order.")
    generate.add_argument("arxiv")

    export = sub.add_parser("export", help="Write an Obsidian vault zip for a cached or new roadmap.")
    export.add_argument("arxiv")
    export.add_argument("-o", "--output", default="roadmap.zip")

    serve = sub.add_parser("serve", help="Run the HTTP API.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    settings = Settings()
    if args.database_url:
        settings = settings.model_copy(update={"database_url": args.database_url})
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.command == "serve":
        app = create_app(build_runtime(settings))
        uvicorn.run(app, host=args.host, port=args.port)
        return
    if args.command == "generate":
        asyncio.run(_generate(settings, args.arxiv))
        return
    asyncio.run(_export(settings, args.arxiv, args.output))


async def _generate(settings: Settings, raw_id: str) -> None:
    runtime = build_runtime(settings)
    try:
        roadmap_id = await _ensure(runtime, raw_id)
        roadmap = runtime.store.load_roadmap(roadmap_id)
        by_topic = {topic.id: topic for topic in roadmap.topics}
        by_paper = {paper.canonical_id: paper for paper in roadmap.ancestors}
        for item in learning_path(roadmap):
            if item.kind == "topic":
                topic = by_topic[item.id]
                print(f"{topic.position + 1}. {topic.name}  [{topic.essentiality}, difficulty {topic.difficulty}]")
            else:
                paper = by_paper[item.id]
                print(f"   paper: {paper.title}  [{paper.role}, {paper.reading_minutes} min]")
    finally:
        await runtime.http.aclose()


async def _export(settings: Settings, raw_id: str, output: str) -> None:
    runtime = build_runtime(settings)
    try:
        roadmap_id = await _ensure(runtime, raw_id)
        roadmap = runtime.store.load_roadmap(roadmap_id)
        payload = zip_vault(build_vault(roadmap))
        with open(output, "wb") as handle:
            handle.write(payload)
        print(output)
    finally:
        await runtime.http.aclose()


async def _ensure(runtime, raw_id: str) -> str:
    arxiv_id = parse_arxiv_id(raw_id)
    if arxiv_id.version is None:
        paper = await runtime.pipeline.clients.arxiv.fetch_metadata(arxiv_id)
        if paper.version is None:
            raise SystemExit(f"arXiv did not report a version for {arxiv_id.base}.")
        arxiv_id = arxiv_id.with_version(paper.version)
        runtime.store.upsert_paper(paper)
    import uuid

    roadmap_id = runtime.store.create_roadmap(str(uuid.uuid4()), arxiv_id.canonical)
    job = runtime.store.get_job(roadmap_id)
    if job and job[1] == "ready":
        return roadmap_id
    await runtime.pipeline.run(roadmap_id, arxiv_id)
    job = runtime.store.get_job(roadmap_id)
    if job is None or job[1] != "ready":
        detail = job[2] if job else "missing job"
        raise SystemExit(detail or "generation failed")
    return roadmap_id


if __name__ == "__main__":
    main()
