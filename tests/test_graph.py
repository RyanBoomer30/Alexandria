from paperpath.domain.graph import GraphConfig, build_learning_graph
from paperpath.domain.models import Edge, EdgeSource, Essentiality, Topic, TopicOrigin


def _topic(
    topic_id: str,
    name: str,
    difficulty: int,
    essentiality: Essentiality,
    origin: TopicOrigin = TopicOrigin.EXTRACTED,
) -> Topic:
    return Topic(id=topic_id, name=name, difficulty=difficulty, essentiality=essentiality, origin=origin)


def _edge(src: str, dst: str, confidence: float) -> Edge:
    return Edge(prerequisite_id=src, dependent_id=dst, confidence=confidence, source=EdgeSource.VERIFIED)


def test_orders_by_difficulty_then_essentiality_and_drops_weak_edges() -> None:
    topics = [
        _topic("hard", "Hard essential", 5, Essentiality.ESSENTIAL),
        _topic("easy-support", "Easy support", 1, Essentiality.SUPPORTING),
        _topic("easy-essential", "Easy essential", 1, Essentiality.ESSENTIAL),
    ]
    edges = [
        _edge("easy-essential", "hard", 0.9),
        _edge("easy-support", "hard", 0.2),
    ]
    result = build_learning_graph(topics, edges, GraphConfig(confidence_threshold=0.7, difficulty_floor=1))
    assert result.ordered_ids == ["easy-essential", "easy-support", "hard"]
    assert [(edge.prerequisite_id, edge.dependent_id) for edge in result.kept_edges] == [("easy-essential", "hard")]
    assert result.dropped_edges[0].drop_reason == "below_confidence"
    assert result.levels["hard"] == 1


def test_breaks_cycles_by_removing_the_weakest_edge() -> None:
    topics = [
        _topic("a", "A", 3, Essentiality.ESSENTIAL),
        _topic("b", "B", 3, Essentiality.ESSENTIAL),
        _topic("c", "C", 2, Essentiality.ESSENTIAL),
    ]
    edges = [_edge("a", "b", 0.9), _edge("b", "a", 0.4), _edge("c", "a", 0.85)]
    result = build_learning_graph(
        topics,
        edges,
        GraphConfig(confidence_threshold=0.3, difficulty_floor=1, max_depth=6),
    )
    dropped = {(edge.prerequisite_id, edge.dependent_id): edge.drop_reason for edge in result.dropped_edges}
    assert dropped[("b", "a")] == "cycle"
    assert result.ordered_ids.index("c") < result.ordered_ids.index("a") < result.ordered_ids.index("b")


def test_difficulty_floor_does_not_expand_easy_topics() -> None:
    topics = [
        _topic("sgd", "SGD", 3, Essentiality.SUPPORTING),
        _topic("clip", "Gradient clipping", 1, Essentiality.INCIDENTAL),
    ]
    result = build_learning_graph(topics, [_edge("sgd", "clip", 0.95)], GraphConfig(difficulty_floor=1))
    assert result.kept_edges == []
    assert result.dropped_edges[0].drop_reason == "difficulty_floor"


def test_depth_cap_stops_the_chain_before_the_next_hop() -> None:
    topics = [
        _topic("calculus", "Calculus", 2, Essentiality.SUPPORTING),
        _topic("linear", "Linear algebra", 3, Essentiality.ESSENTIAL),
        _topic("attention", "Attention", 4, Essentiality.ESSENTIAL),
        _topic("transformer", "Transformer", 5, Essentiality.ESSENTIAL),
    ]
    edges = [
        _edge("calculus", "linear", 0.9),
        _edge("linear", "attention", 0.9),
        _edge("attention", "transformer", 0.95),
    ]
    result = build_learning_graph(topics, edges, GraphConfig(max_depth=2, difficulty_floor=1))
    kept = {(edge.prerequisite_id, edge.dependent_id) for edge in result.kept_edges}
    assert ("attention", "transformer") in kept
    assert ("linear", "attention") in kept
    assert ("calculus", "linear") not in kept
    assert any(edge.drop_reason == "max_depth" for edge in result.dropped_edges)


def test_expanded_topics_past_the_cap_are_removed_from_the_order() -> None:
    topics = [
        _topic("goal", "Goal", 5, Essentiality.ESSENTIAL),
        _topic("deep", "Deep background", 4, Essentiality.SUPPORTING, origin=TopicOrigin.EXPANDED),
    ]
    # deep is a prerequisite of goal, so its depth is 1. Raise the chain with a middle extracted topic
    # and put the expanded topic two hops out with max_depth 0, which drops every prerequisite edge
    # of the anchor and leaves the expanded topic at depth 1 only if the edge remains.
    result = build_learning_graph(
        topics,
        [_edge("deep", "goal", 0.9)],
        GraphConfig(max_depth=0, difficulty_floor=1),
    )
    assert "deep" not in result.ordered_ids
    assert "goal" in result.ordered_ids
