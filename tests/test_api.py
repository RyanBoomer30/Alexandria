import io
import zipfile

import httpx
from httpx import ASGITransport

from paperpath.app import create_app
from paperpath.config import Settings
from paperpath.pipeline.wiring import build_runtime
from tests.fakes import fake_clients


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/paperpath.db",
        data_dir=tmp_path / "data",
        inline_jobs=True,
        arxiv_min_interval_seconds=0,
    )


async def test_generate_personalize_and_export(tmp_path) -> None:
    settings = _settings(tmp_path)
    runtime = build_runtime(settings, clients=fake_clients())
    app = create_app(runtime)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200

        created = await client.post("/v1/roadmaps", json={"arxiv": "https://arxiv.org/abs/1706.03762v7"})
        assert created.status_code == 200
        body = created.json()
        assert body["status"] == "ready"
        roadmap_id = body["id"]

        again = await client.post("/v1/roadmaps", json={"arxiv": "1706.03762v7"})
        assert again.json()["id"] == roadmap_id
        assert runtime.pipeline.clients.frontier.calls.count("topic_extraction") == 1

        loaded = await client.get(f"/v1/roadmaps/{roadmap_id}")
        names = [topic["name"] for topic in loaded.json()["topics"]]
        assert names == ["Linear algebra", "Attention", "Transformer"]
        assert loaded.json()["path"][1]["kind"] == "paper"
        assert loaded.json()["resources"][0]["verified"] is True

        diagnostic = await client.get(f"/v1/roadmaps/{roadmap_id}/diagnostic")
        assert len(diagnostic.json()["questions"]) == 3

        pruned = await client.post(
            f"/v1/roadmaps/{roadmap_id}/personalize",
            json={"user_id": "ada", "known_topic_ids": ["linear-algebra"]},
        )
        assert pruned.json()["pruned_topics"] == ["linear-algebra"]
        viewed = await client.get(f"/v1/roadmaps/{roadmap_id}", params={"user_id": "ada"})
        assert [topic["name"] for topic in viewed.json()["topics"]] == ["Attention", "Transformer"]

        progress = await client.post(
            f"/v1/roadmaps/{roadmap_id}/progress",
            json={"user_id": "ada", "topic_id": "attention", "status": "done"},
        )
        assert progress.json()["progress"]["attention"] == "done"

        exported = await client.get(f"/v1/roadmaps/{roadmap_id}/export", params={"user_id": "ada"})
        assert exported.status_code == 200
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            names = archive.namelist()
        assert "Roadmap.canvas" in names
        assert "Linear algebra.md" not in names
        assert any(name.startswith("Papers/") for name in names)

        missing = await client.post("/v1/roadmaps", json={"arxiv": "definitely not an id"})
        assert missing.status_code == 422
