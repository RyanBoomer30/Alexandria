from datetime import datetime

from paperpath.domain.models import (
    AncestorPaper,
    Edge,
    EdgeSource,
    Essentiality,
    Paper,
    PaperRole,
    PaperTopic,
    Relation,
    Resource,
    ResourceType,
    Roadmap,
    SourceType,
    Topic,
)
from paperpath.export.vault import build_vault, validate_vault, zip_vault


def _roadmap() -> Roadmap:
    paper = Paper(
        key="1706.03762v7",
        arxiv_id="1706.03762",
        version=7,
        title="Attention Is All You Need",
        abstract="Transformers.",
        source_type=SourceType.LATEX,
        fetched_at=datetime.now().astimezone(),
    )
    topics = [
        Topic(
            id="l2-l1",
            name="L2/L1 norms",
            essentiality=Essentiality.SUPPORTING,
            difficulty=2,
            why_it_matters="They measure size.",
            usage_description="Used in the residual.",
            position=0,
            level=0,
        ),
        Topic(
            id="attention",
            name="Attention",
            essentiality=Essentiality.ESSENTIAL,
            difficulty=4,
            why_it_matters="This replaces recurrence.",
            usage_description="The core operation.",
            position=1,
            level=1,
        ),
    ]
    return Roadmap(
        id="job",
        paper=paper,
        topics=topics,
        edges=[
            Edge(
                prerequisite_id="l2-l1",
                dependent_id="attention",
                confidence=0.9,
                source=EdgeSource.VERIFIED,
                kept=True,
            )
        ],
        ancestors=[
            AncestorPaper(
                canonical_id="arxiv:1409.0473",
                arxiv_id="1409.0473",
                title="Align and Translate",
                year=2014,
                url="https://arxiv.org/abs/1409.0473",
                role=PaperRole.FOUNDATIONAL,
                reading_minutes=40,
                priority=1.2,
                depth=1,
                why_it_matters="This is where attention for translation came from.",
            )
        ],
        paper_topics=[
            PaperTopic(
                paper_id="arxiv:1409.0473",
                topic_id="attention",
                relation=Relation.INTRODUCED,
                confidence=0.9,
            )
        ],
        resources=[
            Resource(
                topic_id="attention",
                type=ResourceType.WIKIPEDIA,
                url="https://en.wikipedia.org/wiki/Attention",
                title="Attention",
                verified=True,
                excerpt="Attention is a cognitive process.",
                attribution="Excerpt from the Wikipedia article, available under CC BY-SA.",
            )
        ],
    )


def test_vault_links_resolve_and_filenames_are_safe() -> None:
    files = build_vault(_roadmap())
    assert validate_vault(files) == []
    assert "L2 L1 norms.md" in files
    assert any(name.startswith("Papers/") for name in files)
    note = files["Attention.md"]
    assert "[[L2 L1 norms]]" in note
    assert "CC BY-SA" in note
    assert "type: topic" in note
    payload = zip_vault(files)
    assert payload[:2] == b"PK"


def test_validation_catches_a_broken_wikilink() -> None:
    files = build_vault(_roadmap())
    files["Attention.md"] = files["Attention.md"].replace("[[L2 L1 norms]]", "[[Missing topic]]")
    errors = validate_vault(files)
    assert any("Missing topic" in error for error in errors)
