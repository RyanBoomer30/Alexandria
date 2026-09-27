"""Apply the deterministic learning-graph build to verified edges."""

from paperpath.domain.graph import GraphConfig, build_learning_graph
from paperpath.pipeline.context import RunContext


class GraphStage:
    name = "graph"

    async def run(self, ctx: RunContext) -> None:
        pending = [edge for edge in ctx.edges if edge.drop_reason is None]
        already_dropped = [edge for edge in ctx.edges if edge.drop_reason is not None]
        result = build_learning_graph(
            ctx.topics,
            pending,
            GraphConfig(
                confidence_threshold=ctx.settings.confidence_threshold,
                max_depth=ctx.settings.max_topic_depth,
                difficulty_floor=ctx.settings.difficulty_floor,
            ),
        )
        position = {topic_id: index for index, topic_id in enumerate(result.ordered_ids)}
        ordered = set(result.ordered_ids)
        ctx.topics = [
            topic.model_copy(
                update={
                    "position": position.get(topic.id, topic.position),
                    "level": result.levels.get(topic.id, 0),
                    "included": topic.id in ordered,
                }
            )
            for topic in ctx.topics
        ]
        ctx.edges = [*result.kept_edges, *result.dropped_edges, *already_dropped]
