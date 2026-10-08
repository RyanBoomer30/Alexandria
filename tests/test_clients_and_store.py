from datetime import datetime

import httpx

from paperpath.clients.frontier import FrontierClient
from paperpath.clients.jev import JevClient
from paperpath.config import Settings
from paperpath.db import create_all, make_engine, make_session_factory
from paperpath.db.repository import Store
from paperpath.domain.models import Edge, EdgeSource, Essentiality, Paper, Roadmap, SourceType, Topic, TopicStatus
from paperpath.judgments.catalog import DIFFICULTY, ESSENTIALITY
from paperpath.judgments.parse import NoulAnswer, interpret_jev


def test_store_roundtrip(tmp_path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path}/paperpath.db")
    create_all(engine)
    store = Store(make_session_factory(engine))
    store.create_roadmap("job-1", "1706.03762v7")
    roadmap = Roadmap(
        id="job-1",
        paper=Paper(
            key="1706.03762v7",
            arxiv_id="1706.03762",
            version=7,
            title="Attention",
            abstract="Abstract",
            source_type=SourceType.LATEX,
            fetched_at=datetime.now().astimezone(),
        ),
        topics=[Topic(id="attention", name="Attention", essentiality=Essentiality.ESSENTIAL, difficulty=4, position=0)],
        edges=[
            Edge(
                prerequisite_id="attention",
                dependent_id="attention",
                confidence=0.2,
                source=EdgeSource.VERIFIED,
                kept=False,
                drop_reason="self_loop",
            )
        ],
    )
    store.save_roadmap(roadmap)
    loaded = store.load_roadmap("job-1")
    assert loaded.paper.title == "Attention"
    assert loaded.topics[0].essentiality is Essentiality.ESSENTIAL
    assert loaded.edges[0].drop_reason == "self_loop"
    assert store.get_job_by_paper("1706.03762v7")[1] == "ready"

    user = store.get_user("local", "1706.03762v7")
    user = user.model_copy(update={"pruned_topics": ["attention"], "progress": {"attention": TopicStatus.DONE}})
    store.save_user(user)
    again = store.get_user("local", "1706.03762v7")
    assert again.pruned_topics == ["attention"]
    assert again.progress["attention"] is TopicStatus.DONE


def test_interpret_noul_uses_the_yes_threshold() -> None:
    answer = interpret_jev(ESSENTIALITY, {"type": "noul", "noul": 0.96}, yes_threshold=0.7)
    assert isinstance(answer, NoulAnswer)
    assert answer.yes is True
    weak = interpret_jev(ESSENTIALITY, {"type": "noul", "noul": 0.62}, yes_threshold=0.7)
    assert isinstance(weak, NoulAnswer)
    assert weak.yes is False


async def test_jev_client_posts_the_decisions_contract() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "model": "typesafe/jev-1.13",
                "answers": {
                    "essentiality": {
                        "type": "choice",
                        "choice": "essential",
                        "confidence": 0.8,
                        "probabilities": {"essential": 0.8, "supporting": 0.2, "incidental": 0},
                    },
                    "difficulty": {
                        "type": "score",
                        "score": 2.1,
                        "confidence": 0.7,
                        "probabilities": {"2": 0.9},
                    },
                },
                "usage": {"input_tokens": 12, "output_tokens": 4, "cost": 0.0002},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = JevClient(
            http,
            base_url="https://openrouter.ai/api/alpha",
            api_key="test-key",
            model="typesafe/jev-1.13",
            yes_threshold=0.7,
            app_name="PaperPath",
        )
        answers = await client.decide(
            questions=[ESSENTIALITY, DIFFICULTY],
            state={"topic": "Attention"},
            call_name="topic_judgments",
        )
    assert seen["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert seen["auth"] == "Bearer test-key"
    assert '"type":"choice"' in seen["body"]
    assert '"type":"score"' in seen["body"]
    assert answers["essentiality"].choice == "essential"
    assert answers["difficulty"].level == 3


async def test_frontier_client_strips_json_fences() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "```json\n{\"topics\": []}\n```"}}], "usage": {}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FrontierClient(http, base_url="https://openrouter.ai/api/v1", api_key="k", model="test")
        parsed = await client.complete_json(system="sys", user="user", call_name="topic_extraction")
    assert parsed == {"topics": []}


def test_settings_ignore_empty_env(monkeypatch) -> None:
    monkeypatch.delenv("PAPERPATH_OPENROUTER_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.ancestor_max_depth == 2
    assert settings.jev_model == "typesafe/jev-1.13"
