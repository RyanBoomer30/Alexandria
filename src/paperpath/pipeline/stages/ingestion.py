"""Fetch metadata and the best available text for one arXiv version."""

import asyncio
import logging
from pathlib import Path

from paperpath.clients.source import (
    html_to_text,
    read_latex_source,
    sections_from_plain,
    unpack_arxiv_source,
)
from paperpath.domain.models import SourceType
from paperpath.errors import IngestionError
from paperpath.pipeline.context import RunContext

logger = logging.getLogger(__name__)


class IngestionStage:
    name = "ingestion"

    async def run(self, ctx: RunContext) -> None:
        paper = ctx.store.get_paper(ctx.arxiv_id.canonical)
        if paper is None or not paper.title:
            paper = await ctx.clients.arxiv.fetch_metadata(ctx.arxiv_id)
        ctx.arxiv_id = ctx.arxiv_id.with_version(paper.version or ctx.arxiv_id.version or 1)
        if paper.version is None:
            paper.version = ctx.arxiv_id.version
            paper.key = ctx.arxiv_id.canonical

        dest = ctx.settings.data_dir / "sources" / ctx.arxiv_id.filename_token
        sections = await _from_latex(ctx, dest)
        source_type = SourceType.LATEX
        if not sections:
            sections, source_type = await _from_html(ctx)
        if not sections and ctx.clients.pdf.available:
            sections, source_type = await _from_pdf(ctx, dest)
        if not sections:
            logger.warning("No full text for %s; continuing from the abstract", ctx.arxiv_id.canonical)
            sections = sections_from_plain(paper.abstract)
            source_type = SourceType.METADATA_ONLY

        text_path = dest / "plain.txt"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(_render(paper.title, paper.abstract, sections), encoding="utf-8")
        paper.source_type = source_type
        paper.text_path = str(text_path)
        ctx.paper = paper
        ctx.sections = sections
        ctx.store.upsert_paper(paper)


async def _from_latex(ctx: RunContext, dest: Path) -> list:
    try:
        blob = await ctx.clients.arxiv.fetch_source(ctx.arxiv_id)
    except IngestionError:
        logger.warning("arXiv source download failed for %s", ctx.arxiv_id.canonical, exc_info=True)
        return []
    if not blob:
        return []
    try:
        tex_files = await asyncio.to_thread(unpack_arxiv_source, blob, dest)
        return await asyncio.to_thread(read_latex_source, tex_files)
    except IngestionError:
        logger.warning("Could not unpack LaTeX for %s", ctx.arxiv_id.canonical, exc_info=True)
        return []


async def _from_html(ctx: RunContext) -> tuple[list, SourceType]:
    html = await ctx.clients.arxiv.fetch_html(ctx.arxiv_id)
    if not html:
        return [], SourceType.HTML
    text = html_to_text(html)
    if len(text) < 400:
        return [], SourceType.HTML
    return sections_from_plain(text), SourceType.HTML


async def _from_pdf(ctx: RunContext, dest: Path) -> tuple[list, SourceType]:
    pdf = await ctx.clients.arxiv.fetch_pdf(ctx.arxiv_id)
    if not pdf:
        return [], SourceType.PDF
    try:
        text = await ctx.clients.pdf.extract(pdf)
    except Exception:
        logger.warning("PDF extraction failed for %s", ctx.arxiv_id.canonical, exc_info=True)
        return [], SourceType.PDF
    if not text.strip():
        return [], SourceType.PDF
    (dest / "paper.pdf").parent.mkdir(parents=True, exist_ok=True)
    return sections_from_plain(text), SourceType.PDF


def _render(title: str, abstract: str, sections: list) -> str:
    parts = [title, "", abstract, ""]
    for section in sections:
        parts.append(f"{'#' * section.level} {section.title}")
        parts.append(section.text)
        parts.append("")
    return "\n".join(parts).strip() + "\n"
