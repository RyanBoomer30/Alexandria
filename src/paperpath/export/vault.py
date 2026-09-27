"""Obsidian vault: one note per topic, paper notes, an index, and a canvas."""

import io
import json
import re
import zipfile
from typing import Any

import yaml

from paperpath.domain.models import (
    AncestorPaper,
    Essentiality,
    Relation,
    Roadmap,
    Topic,
    TopicStatus,
    UserRoadmap,
)
from paperpath.domain.ordering import learning_path
from paperpath.errors import PaperPathError

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIKILINK = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_TOPIC_KEYS = ("type", "topic", "aliases", "difficulty", "essentiality", "prerequisites", "status", "paper")
_PAPER_KEYS = ("type", "title", "canonical_id", "role", "reading_time", "status")
_INDEX_KEYS = ("type", "paper", "title")


class VaultError(PaperPathError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Obsidian vault failed validation: " + "; ".join(errors))


def build_vault(roadmap: Roadmap, user: UserRoadmap | None = None) -> dict[str, str]:
    topics = roadmap.included_topics()
    names = _filenames(roadmap.paper.title, topics, roadmap.ancestors)
    progress = user.progress if user else {}
    files: dict[str, str] = {}
    files[names.index] = _index(roadmap, names, progress)
    for topic in topics:
        files[f"{names.topics[topic.id]}.md"] = _topic_note(roadmap, topic, names, progress)
    for paper in roadmap.ancestors:
        path = names.papers[paper.canonical_id]
        files[f"{path}.md"] = _paper_note(roadmap, paper, names, progress)
    files["Roadmap.canvas"] = _canvas(roadmap, names)
    return files


def validate_vault(files: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for path, text in files.items():
        if not path.endswith(".md"):
            continue
        meta, _body = _split_frontmatter(text)
        if meta is None:
            errors.append(f"{path} is missing frontmatter")
            continue
        kind = str(meta.get("type"))
        required = {"topic": _TOPIC_KEYS, "paper": _PAPER_KEYS, "index": _INDEX_KEYS}.get(kind)
        if required is None:
            errors.append(f"{path} has an unknown type {kind!r}")
            continue
        missing = [key for key in required if key not in meta]
        if missing:
            errors.append(f"{path} is missing {', '.join(missing)}")
        for match in _WIKILINK.finditer(text):
            target = match.group(1).strip()
            if f"{target}.md" not in files:
                errors.append(f"{path} links to missing note [[{target}]]")
    if "Roadmap.canvas" not in files:
        errors.append("Roadmap.canvas is missing")
    return errors


def zip_vault(files: dict[str, str]) -> bytes:
    errors = validate_vault(files)
    if errors:
        raise VaultError(errors)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.writestr(path, files[path])
    return buffer.getvalue()


class _Names:
    def __init__(self) -> None:
        self.index = ""
        self.topics: dict[str, str] = {}
        self.papers: dict[str, str] = {}


def _filenames(title: str, topics: list[Topic], papers: list[AncestorPaper]) -> _Names:
    names = _Names()
    used: set[str] = set()
    names.index = _unique(f"00 Roadmap - {_safe(title)}", used) + ".md"
    for topic in topics:
        names.topics[topic.id] = _unique(_safe(topic.name), used)
    paper_used: set[str] = set()
    for paper in papers:
        names.papers[paper.canonical_id] = "Papers/" + _unique(_safe(paper.title), paper_used)
    return names


def _topic_note(roadmap: Roadmap, topic: Topic, names: _Names, progress: dict[str, TopicStatus]) -> str:
    prerequisites = _prerequisite_names(roadmap, topic.id, names)
    papers = _papers_for_topic(roadmap, topic.id, names)
    resources = [item for item in roadmap.resources if item.topic_id == topic.id]
    lines = [
        "## Why this matters",
        "",
        topic.why_it_matters or topic.usage_description,
        "",
        "## In this paper",
        "",
        topic.usage_description or topic.name,
    ]
    if topic.locations:
        lines.extend(["", "Locations: " + ", ".join(topic.locations)])
    lines.extend(["", "## Prerequisites", ""])
    if prerequisites:
        lines.extend(f"- [[{name}]]" for name in prerequisites)
    else:
        lines.append("None. This can be a starting point.")
    if papers:
        lines.extend(["", "## Earlier papers", ""])
        lines.extend(f"- [[{name}]]" for name in papers)
    if resources:
        lines.extend(["", "## Resources", ""])
        for resource in resources:
            lines.append(f"- [{resource.title}]({resource.url})")
            if resource.excerpt:
                lines.extend(["", f"> {resource.excerpt}", ">", f"> {resource.attribution}", ""])
    lines.extend(["", "## Notes", ""])
    status = progress.get(topic.id, TopicStatus.NOT_STARTED)
    return _render(
        {
            "type": "topic",
            "topic": topic.name,
            "aliases": topic.aliases,
            "difficulty": topic.difficulty,
            "essentiality": topic.essentiality.value,
            "prerequisites": prerequisites,
            "status": status.value,
            "paper": roadmap.paper.key,
        },
        "\n".join(lines),
    )


def _paper_note(
    roadmap: Roadmap,
    paper: AncestorPaper,
    names: _Names,
    progress: dict[str, TopicStatus],
) -> str:
    introduced = [
        names.topics[link.topic_id]
        for link in roadmap.paper_topics
        if link.paper_id == paper.canonical_id
        and link.relation == Relation.INTRODUCED
        and link.topic_id in names.topics
    ]
    lineage = [
        names.papers[link.to_paper]
        for link in roadmap.links
        if link.from_paper == paper.canonical_id and link.to_paper in names.papers
    ]
    lines = ["## Why this paper", "", paper.why_it_matters, ""]
    if introduced:
        lines.extend(["## Topics it feeds", ""])
        lines.extend(f"- [[{name}]]" for name in introduced)
        lines.append("")
    if paper.url:
        lines.extend(["## Read", "", f"[{paper.title}]({paper.url})", ""])
    if lineage:
        lines.extend(["## Lineage", ""])
        lines.extend(f"- [[{name}]]" for name in lineage)
        lines.append("")
    status = progress.get(paper.canonical_id, TopicStatus.NOT_STARTED)
    return _render(
        {
            "type": "paper",
            "title": paper.title,
            "canonical_id": paper.canonical_id,
            "arxiv_id": paper.arxiv_id,
            "year": paper.year,
            "role": paper.role.value,
            "reading_time": paper.reading_minutes,
            "status": status.value,
        },
        "\n".join(lines),
    )


def _index(roadmap: Roadmap, names: _Names, progress: dict[str, TopicStatus]) -> str:
    del progress
    lines = [
        f"# {roadmap.paper.title}",
        "",
        f"Learning order for `{roadmap.paper.key}`.",
        "",
        "## Path",
        "",
    ]
    optional: list[str] = []
    by_topic = {topic.id: topic for topic in roadmap.included_topics()}
    by_paper = {paper.canonical_id: paper for paper in roadmap.ancestors}
    step = 1
    for item in learning_path(roadmap):
        if item.kind == "topic":
            topic = by_topic[item.id]
            label = f"[[{names.topics[topic.id]}]]"
            if topic.essentiality == Essentiality.INCIDENTAL:
                optional.append(f"- {label}")
                continue
            mark = "essential" if topic.essentiality == Essentiality.ESSENTIAL else "supporting"
            lines.append(f"{step}. {label} — {mark}")
            step += 1
        else:
            paper = by_paper[item.id]
            minutes = paper.reading_minutes
            lines.append(f"{step}. [[{names.papers[paper.canonical_id]}]] — {paper.role.value}, about {minutes} min")
            step += 1
    if optional:
        lines.extend(["", "## Optional", ""])
        lines.extend(optional)
    lines.extend(
        [
            "",
            "## Progress",
            "",
            "The query below is for the Dataview plugin. Without the plugin it stays as a code block.",
            "",
            "```dataview",
            "TABLE difficulty, essentiality, status",
            "FROM \"\"",
            "WHERE type = \"topic\"",
            "SORT difficulty ASC",
            "```",
            "",
        ]
    )
    return _render(
        {"type": "index", "paper": roadmap.paper.key, "title": roadmap.paper.title},
        "\n".join(lines),
    )


def _canvas(roadmap: Roadmap, names: _Names) -> str:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    rows: dict[int, int] = {}
    for topic in roadmap.included_topics():
        row = rows.get(topic.level, 0)
        rows[topic.level] = row + 1
        color = "1" if topic.essentiality == Essentiality.ESSENTIAL else "2"
        nodes.append(
            {
                "id": f"topic:{topic.id}",
                "type": "file",
                "file": f"{names.topics[topic.id]}.md",
                "x": topic.level * 380,
                "y": row * 160,
                "width": 280,
                "height": 90,
                "color": color,
            }
        )
    for index, paper in enumerate(roadmap.ancestors):
        nodes.append(
            {
                "id": f"paper:{paper.canonical_id}",
                "type": "file",
                "file": f"{names.papers[paper.canonical_id]}.md",
                "x": paper.depth * 380,
                "y": 520 + index * 160,
                "width": 280,
                "height": 90,
                "color": "6",
            }
        )
    for edge in roadmap.kept_edges():
        edges.append(
            {
                "id": f"edge:{edge.prerequisite_id}:{edge.dependent_id}",
                "fromNode": f"topic:{edge.prerequisite_id}",
                "toNode": f"topic:{edge.dependent_id}",
            }
        )
    node_ids = {node["id"] for node in nodes}
    for link in roadmap.links:
        source = f"paper:{link.to_paper}"
        target = f"paper:{link.from_paper}"
        if source in node_ids and target in node_ids:
            edges.append(
                {
                    "id": f"lineage:{link.from_paper}:{link.to_paper}",
                    "fromNode": source,
                    "toNode": target,
                }
            )
    for link in roadmap.paper_topics:
        if link.relation != Relation.INTRODUCED:
            continue
        source = f"paper:{link.paper_id}"
        target = f"topic:{link.topic_id}"
        if source in node_ids and target in node_ids:
            edges.append(
                {
                    "id": f"feeds:{link.paper_id}:{link.topic_id}",
                    "fromNode": source,
                    "toNode": target,
                }
            )
    return json.dumps({"nodes": nodes, "edges": edges}, indent=2) + "\n"


def _prerequisite_names(roadmap: Roadmap, topic_id: str, names: _Names) -> list[str]:
    found = []
    for edge in roadmap.kept_edges():
        if edge.dependent_id == topic_id and edge.prerequisite_id in names.topics:
            found.append(names.topics[edge.prerequisite_id])
    return found


def _papers_for_topic(roadmap: Roadmap, topic_id: str, names: _Names) -> list[str]:
    found = []
    for link in roadmap.paper_topics:
        if link.topic_id == topic_id and link.relation == Relation.INTRODUCED and link.paper_id in names.papers:
            found.append(names.papers[link.paper_id])
    return found


def _render(meta: dict[str, Any], body: str) -> str:
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n\n{body.strip()}\n"


def _split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, text
    try:
        meta = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None, text
    if not isinstance(meta, dict):
        return None, text
    return meta, text[end + 5 :]


def _safe(name: str) -> str:
    cleaned = _UNSAFE.sub(" ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return (cleaned or "untitled")[:120]


def _unique(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    index = 2
    while f"{name} {index}" in used:
        index += 1
    candidate = f"{name} {index}"
    used.add(candidate)
    return candidate
