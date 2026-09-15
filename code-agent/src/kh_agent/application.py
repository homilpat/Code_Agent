import json
from pathlib import Path

from kh_agent.access.service import AuthorizationService
from kh_agent.analysis.python_graph import build_graph, explain, impact
from kh_agent.analysis.risk import RiskPolicy, score_risk
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.identity.service import IdentityService
from kh_agent.repository.identity import RepositoryIdentityResolver
from kh_agent.repository.metadata import MetadataInspector
from kh_agent.repository.snapshot import SourceScanner
from kh_agent.store.database import Database
from kh_agent.store.graphs import GraphStore
from kh_agent.store.registry import Registry


class Application:
    def __init__(
        self,
        db: Database,
        identities: IdentityService | None = None,
        resolver: RepositoryIdentityResolver | None = None,
        inspector: MetadataInspector | None = None,
        scanner: SourceScanner | None = None,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.db = db
        self.identities = identities or IdentityService(db)
        self.resolver = resolver or RepositoryIdentityResolver()
        self.inspector = inspector or MetadataInspector()
        self.registry = Registry(db)
        self.authorization = AuthorizationService(db)
        self.scanner = scanner or SourceScanner()
        self.risk_policy = risk_policy

    def execute(self, command: str, path: Path, target: str | None = None) -> dict:
        identity = self.identities.resolve()
        repository = self.resolver.resolve(path)
        repository_id = self.registry.lookup(repository)
        self.authorization.authorize(identity, repository_id, command)
        # In particular, history and any future cached result never bypass current ACL.
        if command == "history":
            rows = self.db.rows(
                "SELECT sequence,event_id,event_type,payload_json,created_at "
                "FROM audit_events WHERE repository_id=? ORDER BY sequence DESC LIMIT 100",
                (repository_id,),
            )
            return {
                "repository_id": repository_id,
                "events": [
                    {
                        "sequence": row["sequence"],
                        "event_id": row["event_id"],
                        "event_type": row["event_type"],
                        "metadata": json.loads(row["payload_json"]),
                        "created_at": row["created_at"],
                    }
                    for row in reversed(rows)
                ],
            }
        if command == "status":
            current = self.resolver.resolve(path)
            if current != repository:
                raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
            return {"repository_id": repository_id, **self.inspector.inspect(current)}
        if command in ("explain", "impact"):
            if not target:
                raise DomainError(
                    ErrorCode.INVALID_INPUT, "A relative Python file target is required"
                )
            snapshot = self.scanner.scan(repository)
            if self.resolver.resolve(path) != repository:
                raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
            graph = build_graph(snapshot)
            # Recheck after potentially long ingestion, before persistence or display.
            self.authorization.authorize(identity, repository_id, command, "AFTER_SOURCE_INGESTION")
            result = explain(graph, target) if command == "explain" else impact(graph, target)
            if command == "impact" and self.risk_policy:
                # Static candidate imports cannot prove caller/coverage/runtime/security factors.
                # Until those evidence providers exist, preserve their unavailability explicitly.
                result["risk"] = score_risk(
                    self.risk_policy, {}, phase="PRELIMINARY", basis_hash=graph["graph_hash"]
                )
            graph_id = GraphStore(self.db).save(repository_id, identity.user_id, graph)
            return {
                "repository_id": repository_id,
                "graph_id": graph_id,
                "exclusion_count": len(snapshot.exclusions),
                **result,
            }
        raise DomainError(
            ErrorCode.CAPABILITY_NOT_AVAILABLE,
            "This command requires analysis, sandbox or apply components not yet enabled",
        )
