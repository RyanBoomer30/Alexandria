"""Frontier chat model for extraction, edge proposals, and explanations."""

import hashlib
import json
import logging
import time
from collections.abc import Callable

import httpx

from paperpath.clients.http import request_with_retries
from paperpath.domain.models import CallLogEntry
from paperpath.errors import ConfigurationError, UpstreamError
from paperpath.observability import current_roadmap_id

logger = logging.getLogger(__name__)

Recorder = Callable[[CallLogEntry], None]


class FrontierClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        recorder: Recorder | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._recorder = recorder

    @property
    def model(self) -> str:
        return self._model

    async def complete_json(self, *, system: str, user: str, call_name: str) -> dict:
        if not self._api_key:
            raise ConfigurationError("PAPERPATH_OPENROUTER_API_KEY is not set.")
        body = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        started = time.perf_counter()
        response = await request_with_retries(
            self._client,
            "POST",
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("Frontier model returned no message content.") from exc
        parsed = _load_json(content)
        usage = payload.get("usage") or {}
        self._log(
            call_name=call_name,
            request={"system": system, "user": user},
            response=parsed,
            latency_ms=latency_ms,
            cost=_cost(usage),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
        return parsed

    def _log(self, **kwargs: object) -> None:
        if self._recorder is None:
            return
        request = kwargs["request"]
        prefix = kwargs["call_name"]
        entry = CallLogEntry(
            roadmap_id=current_roadmap_id.get(),
            stage=str(prefix),
            model=self._model,
            prefix_hash=_hash({"system": request["system"] if isinstance(request, dict) else ""}),
            prompt_hash=_hash(request),
            inputs=request if isinstance(request, dict) else {},
            outputs=kwargs["response"] if isinstance(kwargs["response"], dict) else {},
            latency_ms=float(kwargs["latency_ms"]),
            cost=kwargs["cost"] if isinstance(kwargs["cost"], (int, float)) else None,
            input_tokens=kwargs["input_tokens"] if isinstance(kwargs["input_tokens"], int) else None,
            output_tokens=kwargs["output_tokens"] if isinstance(kwargs["output_tokens"], int) else None,
        )
        try:
            self._recorder(entry)
        except Exception:
            logger.exception("Failed to write a frontier call log")


def _load_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpstreamError("Frontier model did not return JSON.") from exc
    if not isinstance(parsed, dict):
        raise UpstreamError("Frontier model JSON must be an object.")
    return parsed


def _hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _cost(usage: dict) -> float | None:
    cost = usage.get("cost")
    if isinstance(cost, (int, float)):
        return float(cost)
    return None
