"""In-process progress fanout for generation jobs."""

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    status: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"stage": self.stage, "status": self.status, "detail": self.detail}


class JobHub:
    def __init__(self) -> None:
        self._history: dict[str, list[ProgressEvent]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[ProgressEvent]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def emit(self, roadmap_id: str, event: ProgressEvent) -> None:
        self._history.setdefault(roadmap_id, []).append(event)
        for queue in self._subscribers.get(roadmap_id, []):
            queue.put_nowait(event)

    def subscribe(self, roadmap_id: str) -> asyncio.Queue[ProgressEvent]:
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
        for event in self._history.get(roadmap_id, []):
            queue.put_nowait(event)
        self._subscribers.setdefault(roadmap_id, []).append(queue)
        return queue

    def spawn(self, coro: object) -> None:
        task = asyncio.create_task(coro)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
