"""Turn a Jev or fallback payload into a typed answer."""

from dataclasses import dataclass

from paperpath.judgments.catalog import Question


@dataclass(frozen=True)
class NoulAnswer:
    probability: float
    yes: bool

    @property
    def confidence(self) -> float:
        return abs(self.probability - 0.5) * 2


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    probabilities: dict[str, float]
    confidence: float


@dataclass(frozen=True)
class ScoreAnswer:
    """`level` is 1-based on the criterion list. `score` is Jev's weighted index."""

    score: float
    level: int
    probabilities: dict[str, float]
    confidence: float


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


def interpret_jev(question: Question, raw: dict, *, yes_threshold: float) -> Answer:
    kind = raw.get("type", question.type)
    if kind == "noul":
        probability = _clamp(float(raw["noul"]))
        return NoulAnswer(probability=probability, yes=probability >= yes_threshold)
    if kind == "choice":
        probabilities = {str(key): float(value) for key, value in (raw.get("probabilities") or {}).items()}
        return ChoiceAnswer(
            choice=str(raw["choice"]),
            probabilities=probabilities,
            confidence=float(raw.get("confidence") or 0),
        )
    score = float(raw.get("score", 0))
    probabilities = {str(key): float(value) for key, value in (raw.get("probabilities") or {}).items()}
    return ScoreAnswer(
        score=score,
        level=_score_level(question, score),
        probabilities=probabilities,
        confidence=float(raw.get("confidence") or 0),
    )


def interpret_fallback(question: Question, value: object, *, yes_threshold: float) -> Answer:
    """Frontier models return labels. Confidences are coarse because the model is not calibrated."""
    if question.type == "noul":
        if isinstance(value, dict):
            if "probability" in value:
                probability = _clamp(float(value["probability"]))
            else:
                probability = 0.8 if bool(value.get("yes")) else 0.2
        elif isinstance(value, bool):
            probability = 0.8 if value else 0.2
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            probability = _clamp(float(value))
        else:
            probability = 0.8 if str(value).strip().lower() in {"yes", "true", "1"} else 0.2
        return NoulAnswer(probability=probability, yes=probability >= yes_threshold)
    if question.type == "choice":
        choice = value.get("choice") if isinstance(value, dict) else value
        return ChoiceAnswer(choice=str(choice), probabilities={}, confidence=0.6)
    if isinstance(value, dict):
        raw_score = value.get("level", value.get("score", 3))
    else:
        raw_score = value
    level = int(round(float(raw_score)))
    level = min(5, max(1, level))
    return ScoreAnswer(score=float(level - 1), level=level, probabilities={}, confidence=0.6)


def _score_level(question: Question, score: float) -> int:
    criteria = question.criteria if isinstance(question.criteria, tuple) else ()
    if not criteria:
        return min(5, max(1, int(round(score)) + 1))
    index = int(round(score))
    index = min(len(criteria) - 1, max(0, index))
    return index + 1


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
