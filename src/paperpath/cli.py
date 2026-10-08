"""Command line: generate a roadmap, export a vault, or serve the API."""

import argparse
import asyncio
import logging
import sys
import uuid

import uvicorn

from paperpath.app import create_app
from paperpath.config import Settings
from paperpath.domain.arxiv import parse_arxiv_id
from paperpath.domain.ordering import learning_path
from paperpath.export.vault import build_vault, zip_vault
from paperpath.pipeline.wiring import build_runtime

_USAGE = """\
%(prog)s PAPER_LINK [-o FILE]
       %(prog)s serve [--host HOST] [--port PORT]
"""

_EPILOG = """\
examples:
  python -m paperpath https://arxiv.org/abs/1706.03762
  python -m paperpath https://arxiv.org/pdf/1706.03762.pdf -o roadmap.zip
  python -m paperpath serve
"""


def main(argv: list[str] | None = None) -> None:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    args = parser.parse_args(_prepare_argv(raw))
    if args.serve and (args.paper or args.output):
        parser.error("serve does not take a paper link")
    if not args.serve and not args.paper:
        parser.error("pass an arXiv link, for example: python -m paperpath https://arxiv.org/abs/1706.03762")

    settings = Settings()
    if args.database_url:
        settings = settings.model_copy(update={"database_url": args.database_url})
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.serve:
        app = create_app(build_runtime(settings))
        uvicorn.run(app, host=args.host, port=args.port)
        return
    if args.output:
        asyncio.run(_export(settings, args.paper, args.output))
        return
    asyncio.run(_generate(settings, args.paper))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m paperpath",
        description="Build a learning roadmap for an arXiv paper.",
        usage=_USAGE,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paper",
        nargs="?",
        metavar="PAPER_LINK",
        help="arXiv URL or id (abs, pdf, html, or a bare id)",
    )
    parser.add_argument("-o", "--output", metavar="FILE", help="write an Obsidian vault zip to this path")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=8000, help=argparse.SUPPRESS)
    parser.add_argument("--database-url", default=None)
    return parser


def _prepare_argv(argv: list[str]) -> list[str]:
    """Accept a bare link, and keep the older generate, export, and serve forms."""
    if not argv or argv[0] in {"-h", "--help"}:
        return argv
    if argv[0] == "serve":
        return ["--serve", *argv[1:]]
    if argv[0] == "generate":
        return argv[1:]
    if argv[0] == "export":
        rest = argv[1:]
        if "-o" not in rest and "--output" not in rest:
            rest = [*rest, "-o", "roadmap.zip"]
        return rest
    return argv


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
