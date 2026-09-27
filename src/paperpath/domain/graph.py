"""Learning-graph construction.

Edges point from a prerequisite to the topic that depends on it. The builder
drops weak edges, breaks cycles by removing the lowest-confidence edge, refuses
to expand topics that are already easy or already deep enough, then orders
what remains. Ties break by difficulty, then essentiality, then name.
"""

import heapq
from collections import defaultdict
from dataclasses import dataclass

from paperpath.domain.models import Edge, Essentiality, Topic, TopicOrigin

_ESSENTIALITY_RANK = {
    Essentiality.ESSENTIAL: 0,
    Essentiality.SUPPORTING: 1,
    Essentiality.INCIDENTAL: 2,
}
_INF = 10**9


@dataclass(frozen=True)
class GraphConfig:
    confidence_threshold: float = 0.7
    max_depth: int = 4
    difficulty_floor: int = 1


@dataclass(frozen=True)
class GraphBuildResult:
    ordered_ids: list[str]
    levels: dict[str, int]
    kept_edges: list[Edge]
    dropped_edges: list[Edge]


def build_learning_graph(
    topics: list[Topic],
    edges: list[Edge],
    config: GraphConfig | None = None,
) -> GraphBuildResult:
    config = config or GraphConfig()
    by_id = {topic.id: topic for topic in topics}
    kept: list[Edge] = []
    dropped: list[Edge] = []

    for edge in edges:
        if edge.prerequisite_id not in by_id or edge.dependent_id not in by_id:
            dropped.append(_drop(edge, "unknown_topic"))
        elif edge.prerequisite_id == edge.dependent_id:
            dropped.append(_drop(edge, "self_loop"))
        elif edge.confidence < config.confidence_threshold:
            dropped.append(_drop(edge, "below_confidence"))
        else:
            kept.append(edge)

    kept = _keep_strongest(kept)
    kept, cycle_dropped = _break_cycles(list(by_id), kept)
    dropped.extend(cycle_dropped)
    kept, floor_dropped = _apply_difficulty_floor(kept, by_id, config.difficulty_floor)
    dropped.extend(floor_dropped)
    kept, depth_dropped, excluded = _apply_depth_cap(kept, topics, config.max_depth)
    dropped.extend(depth_dropped)

    ordered, levels = _topo_sort(topics, kept, excluded)
    return GraphBuildResult(
        ordered_ids=ordered,
        levels=levels,
        kept_edges=[edge.model_copy(update={"kept": True, "drop_reason": None}) for edge in kept],
        dropped_edges=dropped,
    )


def _drop(edge: Edge, reason: str) -> Edge:
    return edge.model_copy(update={"kept": False, "drop_reason": reason})


def _keep_strongest(edges: list[Edge]) -> list[Edge]:
    best: dict[tuple[str, str], Edge] = {}
    for edge in edges:
        key = (edge.prerequisite_id, edge.dependent_id)
        current = best.get(key)
        if current is None or edge.confidence > current.confidence:
            best[key] = edge
    return list(best.values())


def _break_cycles(node_ids: list[str], edges: list[Edge]) -> tuple[list[Edge], list[Edge]]:
    remaining = list(edges)
    dropped: list[Edge] = []
    while True:
        cycle = _find_cycle(node_ids, remaining)
        if cycle is None:
            return remaining, dropped
        weakest = min(cycle, key=lambda edge: (edge.confidence, edge.prerequisite_id, edge.dependent_id))
        remaining = [edge for edge in remaining if edge is not weakest]
        dropped.append(_drop(weakest, "cycle"))


def _find_cycle(node_ids: list[str], edges: list[Edge]) -> list[Edge] | None:
    adjacency: dict[str, list[str]] = defaultdict(list)
    lookup: dict[tuple[str, str], Edge] = {}
    for edge in edges:
        adjacency[edge.prerequisite_id].append(edge.dependent_id)
        lookup[(edge.prerequisite_id, edge.dependent_id)] = edge

    color = dict.fromkeys(node_ids, 0)
    stack: list[str] = []
    index: dict[str, int] = {}

    def visit(node: str) -> list[Edge] | None:
        color[node] = 1
        index[node] = len(stack)
        stack.append(node)
        for nxt in adjacency.get(node, []):
            if color.get(nxt, 0) == 0:
                found = visit(nxt)
                if found is not None:
                    return found
            elif color.get(nxt) == 1:
                nodes = stack[index[nxt] :] + [nxt]
                return [lookup[(a, b)] for a, b in zip(nodes, nodes[1:])]
        stack.pop()
        color[node] = 2
        return None

    for node in node_ids:
        if color[node] == 0:
            found = visit(node)
            if found is not None:
                return found
    return None


def _apply_difficulty_floor(
    edges: list[Edge],
    topics: dict[str, Topic],
    floor: int,
) -> tuple[list[Edge], list[Edge]]:
    """Do not spell out prerequisites of a topic that is already at or below the floor."""
    kept: list[Edge] = []
    dropped: list[Edge] = []
    for edge in edges:
        dependent = topics[edge.dependent_id]
        if dependent.difficulty <= floor:
            dropped.append(_drop(edge, "difficulty_floor"))
        else:
            kept.append(edge)
    return kept, dropped


def _apply_depth_cap(
    edges: list[Edge],
    topics: list[Topic],
    max_depth: int,
) -> tuple[list[Edge], list[Edge], set[str]]:
    """Drop edges that would reach more than max_depth hops back from the paper's goals.

    Extracted topics stay in the roadmap. Topics that were added only by recursive
    expansion and land past the cap are marked excluded.
    """
    anchors = _anchors(topics, edges)
    depth = _depths_from_anchors(anchors, edges, [topic.id for topic in topics])
    kept: list[Edge] = []
    dropped: list[Edge] = []
    for edge in edges:
        if depth.get(edge.dependent_id, 0) >= max_depth:
            dropped.append(_drop(edge, "max_depth"))
        else:
            kept.append(edge)

    excluded: set[str] = set()
    for topic in topics:
        topic_depth = depth.get(topic.id)
        if (
            topic.origin == TopicOrigin.EXPANDED
            and topic_depth is not None
            and topic_depth > max_depth
        ):
            excluded.add(topic.id)
    return kept, dropped, excluded


def _anchors(topics: list[Topic], edges: list[Edge]) -> set[str]:
    ids = {topic.id for topic in topics}
    essential = {topic.id for topic in topics if topic.essentiality == Essentiality.ESSENTIAL}
    pool = essential or ids
    used_as_prereq = {
        edge.prerequisite_id
        for edge in edges
        if edge.prerequisite_id in pool and edge.dependent_id in pool
    }
    anchors = pool - used_as_prereq
    return anchors or pool


def _depths_from_anchors(anchors: set[str], edges: list[Edge], node_ids: list[str]) -> dict[str, int]:
    dist = {node: (0 if node in anchors else _INF) for node in node_ids}
    updated = True
    hops = 0
    while updated and hops <= len(node_ids):
        updated = False
        hops += 1
        for edge in edges:
            if edge.dependent_id not in dist or edge.prerequisite_id not in dist:
                continue
            candidate = dist[edge.dependent_id] + 1
            if candidate < dist[edge.prerequisite_id]:
                dist[edge.prerequisite_id] = candidate
                updated = True
    return {node: value for node, value in dist.items() if value < _INF}


def _topo_sort(
    topics: list[Topic],
    edges: list[Edge],
    excluded: set[str],
) -> tuple[list[str], dict[str, int]]:
    included = [topic for topic in topics if topic.id not in excluded]
    indegree = {topic.id: 0 for topic in included}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.prerequisite_id in indegree and edge.dependent_id in indegree:
            adjacency[edge.prerequisite_id].append(edge.dependent_id)
            indegree[edge.dependent_id] += 1

    by_id = {topic.id: topic for topic in included}
    heap = [_sort_key(topic) for topic in included if indegree[topic.id] == 0]
    heapq.heapify(heap)
    ordered: list[str] = []
    levels = {topic.id: 0 for topic in included}

    while heap:
        *_, topic_id = heapq.heappop(heap)
        ordered.append(topic_id)
        for dependent in adjacency[topic_id]:
            levels[dependent] = max(levels[dependent], levels[topic_id] + 1)
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(heap, _sort_key(by_id[dependent]))

    if len(ordered) != len(included):
        leftover = [topic for topic in included if topic.id not in set(ordered)]
        leftover.sort(key=_sort_key)
        ordered.extend(topic.id for topic in leftover)
    return ordered, levels


def _sort_key(topic: Topic) -> tuple[int, int, str, str]:
    return (
        topic.difficulty,
        _ESSENTIALITY_RANK.get(topic.essentiality, 1),
        topic.name.lower(),
        topic.id,
    )
