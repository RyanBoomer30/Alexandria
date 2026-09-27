from datetime import datetime

from paperpath.clients.jev import UnavailablePdfExtractor
from paperpath.clients.wikipedia import WikipediaArticle
from paperpath.domain.ancestors import Candidate, CitationContext, CitationSection
from paperpath.domain.models import Paper, SourceType
from paperpath.judgments.parse import ChoiceAnswer, NoulAnswer, ScoreAnswer
from paperpath.pipeline.context import Clients


class FakeArxiv:
    async def fetch_metadata(self, arxiv_id):
        version = arxiv_id.version or 7
        resolved = arxiv_id.with_version(version)
        return Paper(
            key=resolved.canonical,
            arxiv_id=resolved.base,
            version=version,
            title="Attention Is All You Need",
            abstract="We propose the Transformer.",
            authors=["Vaswani"],
            categories=["cs.CL"],
            source_type=SourceType.METADATA_ONLY,
            fetched_at=datetime.now().astimezone(),
        )

    async def fetch_source(self, arxiv_id):
        return None

    async def fetch_html(self, arxiv_id):
        return "<html><body><p>" + ("The Transformer uses attention. " * 40) + "</p></body></html>"

    async def fetch_pdf(self, arxiv_id):
        return None


class FakeFrontier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete_json(self, *, system: str, user: str, call_name: str) -> dict:
        self.calls.append(call_name)
        if call_name == "topic_extraction":
            return {
                "topics": [
                    {
                        "name": "Linear algebra",
                        "aliases": ["vectors"],
                        "usage_description": "Weights are matrices.",
                        "locations": ["Section 3"],
                        "related_references": [],
                    },
                    {
                        "name": "Attention",
                        "aliases": [],
                        "usage_description": "The model attends over the input.",
                        "locations": ["Section 3.2"],
                        "related_references": ["1409.0473"],
                    },
                    {
                        "name": "Transformer",
                        "aliases": [],
                        "usage_description": "The architecture proposed here.",
                        "locations": ["Section 3"],
                        "related_references": [],
                    },
                ]
            }
        if call_name == "edge_proposal":
            return {
                "edges": [
                    {"prerequisite": "Linear algebra", "dependent": "Attention"},
                    {"prerequisite": "Attention", "dependent": "Transformer"},
                ]
            }
        if call_name == "explanations":
            return {
                "explanations": [
                    {"topic_name": "Linear algebra", "why_it_matters": "Matrices are the weights."},
                    {"topic_name": "Attention", "why_it_matters": "Attention replaces recurrence."},
                    {"topic_name": "Transformer", "why_it_matters": "This is the model itself."},
                ]
            }
        raise AssertionError(call_name)


class FakeJudgments:
    async def decide(self, *, questions, state, call_name: str):
        answers = {}
        for question in questions:
            key = question.key
            if key == "essentiality":
                answers[key] = ChoiceAnswer("essential", {}, 0.9)
            elif key == "difficulty":
                level = {"Linear algebra": 2, "Attention": 4, "Transformer": 5}[state["topic"]]
                answers[key] = ScoreAnswer(float(level - 1), level, {}, 0.9)
            elif key == "prerequisite":
                pair = (state["topic_a"]["name"], state["topic_b"]["name"])
                yes = pair in {("Linear algebra", "Attention"), ("Attention", "Transformer")}
                answers[key] = NoulAnswer(0.93 if yes else 0.05, yes)
            elif key == "wikipedia_match":
                answers[key] = NoulAnswer(0.96, True)
            elif key == "builds_on":
                answers[key] = NoulAnswer(0.91, True)
            elif key == "role":
                answers[key] = ChoiceAnswer("foundational_method", {}, 0.8)
            elif key == "usefulness":
                answers[key] = ScoreAnswer(3.0, 4, {}, 0.8)
            elif key.startswith("introduced:"):
                yes = key == "introduced:attention"
                answers[key] = NoulAnswer(0.9 if yes else 0.1, yes)
            elif key == "user_knows":
                yes = "already know" in state["answer"].lower()
                answers[key] = NoulAnswer(0.9 if yes else 0.2, yes)
            else:
                raise AssertionError(key)
        return answers


class FakeScholar:
    async def references_for_arxiv(self, arxiv_id):
        return [
            Candidate(
                canonical_id="arxiv:1409.0473",
                title="Neural Machine Translation by Jointly Learning to Align and Translate",
                year=2014,
                arxiv_id="1409.0473",
                abstract="Attention lets a decoder focus on the source.",
                url="https://arxiv.org/abs/1409.0473",
                influential=True,
                contexts=(CitationContext(CitationSection.METHOD, "Our method builds on attention."),),
                page_count=8,
            )
        ]

    async def references_for_canonical(self, canonical_id):
        return []


class FakeOpenAlex:
    async def references_for_arxiv(self, arxiv_id):
        return []


class FakeWikipedia:
    async def search(self, query: str, *, limit: int):
        slug = query.replace(" ", "_")
        return [WikipediaArticle(title=query, url=f"https://en.wikipedia.org/wiki/{slug}", extract="Lead. " * 30)]


def fake_clients() -> Clients:
    return Clients(
        arxiv=FakeArxiv(),
        scholar=FakeScholar(),
        openalex=FakeOpenAlex(),
        wikipedia=FakeWikipedia(),
        frontier=FakeFrontier(),
        judgments=FakeJudgments(),
        pdf=UnavailablePdfExtractor(),
    )
