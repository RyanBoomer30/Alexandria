"""Stable Jev question definitions.

Instructions and criteria are constants. Callers put the paper, topic, or
candidate in `state`, which is the part that changes between calls. Keeping
the question text fixed is what makes prompt-cache reuse possible.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Question:
    key: str
    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: dict[str, str] | tuple[str, ...] | None = None

    def to_api(self) -> dict:
        payload: dict = {"type": self.type, "instructions": self.instructions}
        if self.criteria is not None:
            payload["criteria"] = list(self.criteria) if isinstance(self.criteria, tuple) else self.criteria
        return payload


ESSENTIALITY = Question(
    key="essentiality",
    type="choice",
    instructions=(
        "How necessary is state.topic to understanding the paper's main result? "
        "Use state.usage for how the paper actually uses it, not the topic in general."
    ),
    criteria={
        "essential": "The main result cannot be understood without this topic.",
        "supporting": "The topic is used, but a light grasp is enough to follow the main result.",
        "incidental": "The topic is mentioned in passing and is not needed to follow the result.",
    },
)

DIFFICULTY = Question(
    key="difficulty",
    type="score",
    instructions=(
        "How hard is state.topic for a reader who is new to this paper's subfield? "
        "Judge the topic itself, using state.usage only as context for which variant is meant."
    ),
    criteria=(
        "Familiar from a first undergraduate course in the field.",
        "Standard undergraduate material.",
        "Advanced undergraduate or early graduate material.",
        "Graduate material that usually needs a course or a careful textbook chapter.",
        "Research-level material, usually learned from papers rather than textbooks.",
    ),
)

PREREQUISITE = Question(
    key="prerequisite",
    type="noul",
    instructions=(
        "Must a reader understand state.topic_a before state.topic_b? "
        "Say yes only when A is a real prerequisite of B as this paper uses B, not merely related."
    ),
    criteria={
        "true": "A reader who does not understand A cannot understand B as this paper uses B.",
        "false": "A reader can understand B without A, or the link is only a weak association.",
    },
)

WIKIPEDIA_MATCH = Question(
    key="wikipedia_match",
    type="noul",
    instructions=(
        "Does state.article_title, summarized by state.article_lead, refer to the same concept "
        "as state.topic used in state.usage? Reject a page about a different sense of the same word."
    ),
    criteria={
        "true": "The article is about the concept this paper is using.",
        "false": "The article is a different sense, a broader page, or only loosely related.",
    },
)

USER_KNOWS = Question(
    key="user_knows",
    type="noul",
    instructions=(
        "Does state.answer show that the reader already understands state.topic "
        "well enough to skip it before reading this paper?"
    ),
    criteria={
        "true": "The answer shows a working understanding of the topic as the paper uses it.",
        "false": "The answer is missing, vague, or confused about the topic.",
    },
)

BUILDS_ON = Question(
    key="builds_on",
    type="noul",
    instructions=(
        "Does the target paper build directly on the candidate paper's method, "
        "rather than only citing it as background? Use state.citation_contexts."
    ),
    criteria={
        "true": "The target adopts, extends, or relies on the candidate's method.",
        "false": "The citation is background, a comparison, or a passing mention.",
    },
)

PAPER_ROLE = Question(
    key="role",
    type="choice",
    instructions="What role does the candidate paper play for someone learning the target paper?",
    criteria={
        "foundational_method": "It introduced a method the target paper builds on.",
        "survey_or_tutorial": "It is a survey, tutorial, or textbook-like treatment.",
        "benchmark_or_dataset": "It contributes a benchmark, dataset, or evaluation protocol.",
        "background": "It is useful context but not a method, survey, or benchmark.",
    },
)

LEARNER_USEFULNESS = Question(
    key="usefulness",
    type="score",
    instructions=(
        "How useful is the candidate paper as reading for someone working through "
        "state.roadmap_topics on the way to the target paper?"
    ),
    criteria=(
        "Skip it. It will not help this reader.",
        "Optional. A short look is enough.",
        "Useful. Worth reading the relevant sections.",
        "Important. Read it before the target.",
        "Essential lineage. The target is hard to place without it.",
    ),
)


def introduced_question(topic_id: str, topic_name: str) -> Question:
    """One question per topic. The topic name is the only text that changes."""
    return Question(
        key=f"introduced:{topic_id}",
        type="noul",
        instructions=(
            f'Did the candidate paper introduce or first develop "{topic_name}" '
            "as that topic is described in state.topics?"
        ),
        criteria={
            "true": "This paper is where a reader should meet the topic, or it is the original source.",
            "false": "The paper uses the topic but did not introduce it, or it is unrelated.",
        },
    )
