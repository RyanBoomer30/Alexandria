"""Small text helpers shared by ingestion and prompts."""

import re

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG.sub("-", name.lower()).strip("-")
    return slug[:80] or "topic"


def allocate_id(name: str, used: set[str]) -> str:
    base = slugify(name)
    if base not in used:
        used.add(base)
        return base
    index = 2
    while f"{base}-{index}" in used:
        index += 1
    candidate = f"{base}-{index}"
    used.add(candidate)
    return candidate


def prompt_context(title: str, abstract: str, sections: list[tuple[int, str, str]], limit: int) -> str:
    """Build the paper text sent to a model, capped so one paper cannot blow the context."""
    parts = [f"Title: {title}", f"Abstract: {abstract}"]
    for level, heading, body in sections:
        parts.append(f"\n{'#' * max(1, level)} {heading}\n{body}")
    text = "\n".join(parts).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]"
