"""Interleave topics and the papers that introduce them."""

from collections import defaultdict

from paperpath.domain.models import PathItem, Relation, Roadmap


def learning_path(roadmap: Roadmap) -> list[PathItem]:
    topics = roadmap.included_topics()
    position = {topic.id: topic.position for topic in topics}
    introduced_at: dict[str, int] = {}
    for link in roadmap.paper_topics:
        if link.relation != Relation.INTRODUCED or link.topic_id not in position:
            continue
        spot = position[link.topic_id]
        current = introduced_at.get(link.paper_id)
        introduced_at[link.paper_id] = spot if current is None else min(current, spot)

    papers_before: dict[int, list] = defaultdict(list)
    for paper in roadmap.ancestors:
        papers_before[introduced_at.get(paper.canonical_id, 0)].append(paper)

    items: list[PathItem] = []
    for topic in topics:
        anchored = sorted(papers_before.get(topic.position, []), key=lambda paper: (-paper.priority, paper.title))
        for paper in anchored:
            items.append(PathItem(kind="paper", id=paper.canonical_id, level=topic.level))
        items.append(PathItem(kind="topic", id=topic.id, level=topic.level))
    return items
