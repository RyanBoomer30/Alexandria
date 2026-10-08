"""Jev decisions via the OpenRouter Decisions API, with a frontier-model fallback.

Jev returns probabilities for fixed question types. It does not write prose.
When it is unconfigured or a call fails, the same question definitions are sent
to the frontier model so each judgment stays swappable.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable

import httpx

from paperpath.clients.frontier import FrontierClient
from paperpath.clients.http import request_with_retries
from paperpath.config import Settings
from paperpath.domain.models import CallLogEntry
from paperpath.errors import ConfigurationError, UpstreamError
from paperpath.judgments.catalog import Question
from paperpath.judgments.parse import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer, interpret_fallback, interpret_jev
from paperpath.observability import current_roadmap_id

logger = logging.getLogger(__name__)

Recorder = Callable[[CallLogEntry], None]


class JevClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        api_key: str,
        model: str,
        yes_threshold: float,
        app_name: str,
        recorder: Recorder | None = None,
    ) -> None:
        self._client = client
        self._url = f"{base_url.rstrip('/')}/decisions"
        self._api_key = api_key
        self._model = model
        self._yes_threshold = yes_threshold
        self._app_name = app_name
        self._recorder = recorder

    @property
    def model(self) -> str:
        return self._model

    async def decide(
        self,
        *,
        questions: list[Question],
        state: dict,
        call_name: str,
    ) -> dict[str, Answer]:
        if not self._api_key:
            raise ConfigurationError("PAPERPATH_OPENROUTER_API_KEY is not set.")
        body = {
            "model": self._model,
            "state": state,
            "questions": {question.key: question.to_api() for question in questions},
        }
        started = time.perf_counter()
        response = await request_with_retries(
            self._client,
            "POST",
            self._url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://paperpath.local",
                "X-Title": self._app_name,
            },
            json=body,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        payload = response.json()
        raw_answers = payload.get("answers") if isinstance(payload, dict) else None
        if not isinstance(raw_answers, dict):
            raise UpstreamError("Jev returned no answers.")
        parsed = {
            question.key: interpret_jev(question, raw_answers[question.key], yes_threshold=self._yes_threshold)
            for question in questions
            if question.key in raw_answers
        }
        missing = [question.key for question in questions if question.key not in parsed]
        if missing:
            raise UpstreamError(f"Jev omitted answers for {', '.join(missing)}.")
        usage = payload.get("usage") or {}
        self._log(
            call_name=call_name,
            questions=questions,
            state=state,
            outputs={key: _public_answer(value) for key, value in parsed.items()},
            latency_ms=latency_ms,
            cost=usage.get("cost") if isinstance(usage.get("cost"), (int, float)) else None,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        return parsed

    def _log(self, **kwargs: object) -> None:
        if self._recorder is None:
            return
        questions = kwargs["questions"]
        if isinstance(questions, list):
            prefix = [question.to_api() | {"key": question.key} for question in questions]
        else:
            prefix = []
        request = {"questions": prefix, "state": kwargs["state"]}
        entry = CallLogEntry(
            roadmap_id=current_roadmap_id.get(),
            stage=str(kwargs["call_name"]),
            model=self._model,
            prefix_hash=_hash(prefix),
            prompt_hash=_hash(request),
            inputs=request,
            outputs=kwargs["outputs"] if isinstance(kwargs["outputs"], dict) else {},
            latency_ms=float(kwargs["latency_ms"]),
            cost=float(kwargs["cost"]) if isinstance(kwargs["cost"], (int, float)) else None,
            input_tokens=kwargs["input_tokens"] if isinstance(kwargs["input_tokens"], int) else None,
            output_tokens=kwargs["output_tokens"] if isinstance(kwargs["output_tokens"], int) else None,
        )
        try:
            self._recorder(entry)
        except Exception:
            logger.exception("Failed to write a Jev call log")


class JudgmentClient:
    """Prefer Jev. Fall back to the frontier model per the question catalog when asked."""

    def __init__(self, jev: JevClient, frontier: FrontierClient, settings: Settings) -> None:
        self._jev = jev
        self._frontier = frontier
        self._settings = settings

    async def decide(
        self,
        *,
        questions: list[Question],
        state: dict,
        call_name: str,
    ) -> dict[str, Answer]:
        if self._settings.jev_configured:
            try:
                return await self._jev.decide(questions=questions, state=state, call_name=call_name)
            except (UpstreamError, ConfigurationError):
                if self._settings.jev_fallback != "frontier":
                    raise
                logger.warning("Jev call %s failed; using the frontier model", call_name)
        elif self._settings.jev_fallback != "frontier":
            raise ConfigurationError("PAPERPATH_OPENROUTER_API_KEY is not set and Jev fallback is disabled.")
        return await self._decide_with_frontier(questions=questions, state=state, call_name=call_name)

    async def _decide_with_frontier(
        self,
        *,
        questions: list[Question],
        state: dict,
        call_name: str,
    ) -> dict[str, Answer]:
        system = (
            "You are standing in for a decision model. Answer every question about the state. "
            "Return JSON of the form {\"answers\": {\"<question key>\": <value>}}. "
            "For type noul, value is a probability between 0 and 1 that the answer is yes. "
            "For type choice, value is one of the criteria keys. "
            "For type score, value is an integer level starting at 1 for the first criterion."
        )
        user = json.dumps(
            {
                "questions": {question.key: question.to_api() for question in questions},
                "state": state,
            },
            ensure_ascii=False,
            default=str,
        )
        parsed = await self._frontier.complete_json(
            system=system,
            user=user,
            call_name=f"{call_name}.frontier_fallback",
        )
        raw = parsed.get("answers") if isinstance(parsed.get("answers"), dict) else parsed
        if not isinstance(raw, dict):
            raise UpstreamError("Frontier fallback did not return answers.")
        return {
            question.key: interpret_fallback(
                question,
                raw.get(question.key),
                yes_threshold=self._settings.noul_yes_threshold,
            )
            for question in questions
        }


class UnavailablePdfExtractor:
    """PDF fallback slot. GROBID or Marker can replace this without touching the pipeline."""

    available = False

    async def extract(self, pdf_bytes: bytes) -> str:
        raise ConfigurationError(
            "PDF text extraction is not configured. LaTeX and HTML were both unavailable."
        )


def _public_answer(answer: Answer) -> dict:
    if isinstance(answer, NoulAnswer):
        return {"type": "noul", "probability": answer.probability, "yes": answer.yes}
    if isinstance(answer, ChoiceAnswer):
        return {"type": "choice", "choice": answer.choice, "confidence": answer.confidence}
    if isinstance(answer, ScoreAnswer):
        return {"type": "score", "score": answer.score, "level": answer.level}
    return {}


def _hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
