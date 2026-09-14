import json

from kh_agent.core.canonical import canonical_hash
from kh_agent.core.clock import utc_now
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import GraphSnapshotId
from kh_agent.store.database import Database, append_event


class GraphStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, repository_id: str, user_id: str, graph: dict) -> str:
        graph_value = {key: value for key, value in graph.items() if key != "graph_hash"}
        if canonical_hash(graph_value, "python-graph-v1").digest != graph["graph_hash"]:
            raise DomainError(ErrorCode.INVALID_INPUT, "Graph binding mismatch")
        encoded = json.dumps(graph, sort_keys=True, ensure_ascii=True)
        if len(encoded) > 4 * 1024 * 1024:
            raise DomainError(ErrorCode.INVALID_INPUT, "Graph persistence quota exceeded")
        with self.db.transaction() as conn:
            prior = conn.execute(
                "SELECT graph_id FROM graph_snapshots WHERE repository_id=? AND graph_hash=?",
                (repository_id, graph["graph_hash"]),
            ).fetchone()
            if prior:
                return prior["graph_id"]
            graph_id = str(GraphSnapshotId.new())
            conn.execute(
                "INSERT INTO graph_snapshots VALUES (?,?,?,?,?,?,?)",
                (
                    graph_id,
                    repository_id,
                    graph["source_snapshot_hash"],
                    graph["graph_hash"],
                    graph["builder_version"],
                    encoded,
                    utc_now(),
                ),
            )
            append_event(
                conn,
                event_type="GRAPH_REFRESHED",
                aggregate_type="graph",
                aggregate_id=graph_id,
                repository_id=repository_id,
                user_id=user_id,
                payload={
                    "graph_hash": graph["graph_hash"],
                    "source_snapshot_hash": graph["source_snapshot_hash"],
                },
            )
            return graph_id
