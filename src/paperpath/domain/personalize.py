"""Per-user views over a cached roadmap. Personalization only removes topics."""

from paperpath.domain.models import (
    DiagnosticQuestion,
    Essentiality,
    Roadmap,
    TopicStatus,
    UserRoadmap,
)


def diagnostic_questions(roadmap: Roadmap, limit: int) -> list[DiagnosticQuestion]:
    """Ask about the essential, harder topics. Those change the roadmap the most."""
    ranked = sorted(
        roadmap.included_topics(),
        key=lambda topic: (
            0 if topic.essentiality == Essentiality.ESSENTIAL else 1,
            -topic.difficulty,
            topic.position,
        ),
    )
    questions: list[DiagnosticQuestion] = []
    for topic in ranked[:limit]:
        hint = topic.usage_description or topic.name
        questions.append(
            DiagnosticQuestion(
                topic_id=topic.id,
                topic_name=topic.name,
                prompt=f"What is {topic.name}, and how does this paper use it? ({hint})",
            )
        )
    return questions


def apply_progress(user: UserRoadmap, topic_id: str, status: TopicStatus) -> UserRoadmap:
    progress = dict(user.progress)
    progress[topic_id] = status
    return user.model_copy(update={"progress": progress})


def prune_known(user: UserRoadmap, known_topic_ids: list[str]) -> UserRoadmap:
    pruned = list(dict.fromkeys([*user.pruned_topics, *known_topic_ids]))
    return user.model_copy(update={"pruned_topics": pruned})


def view_for_user(roadmap: Roadmap, user: UserRoadmap | None) -> Roadmap:
    if user is None or not user.pruned_topics:
        return roadmap
    hidden = set(user.pruned_topics)
    topics = [topic for topic in roadmap.topics if topic.id not in hidden]
    edges = [
        edge
        for edge in roadmap.edges
        if edge.prerequisite_id not in hidden and edge.dependent_id not in hidden
    ]
    resources = [item for item in roadmap.resources if item.topic_id not in hidden]
    paper_topics = [item for item in roadmap.paper_topics if item.topic_id not in hidden]
    return roadmap.model_copy(
        update={
            "topics": topics,
            "edges": edges,
            "resources": resources,
            "paper_topics": paper_topics,
        }
    )
