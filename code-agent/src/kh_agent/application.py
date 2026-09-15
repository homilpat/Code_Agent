import json
from collections.abc import Callable
from pathlib import Path

from kh_agent.access.gates import require_mutation_target
from kh_agent.access.service import AuthorizationService
from kh_agent.analysis.python_graph import build_graph, explain, impact
from kh_agent.analysis.risk import RiskPolicy, score_risk
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.identity.service import IdentityService
from kh_agent.repository.identity import RepositoryIdentity, RepositoryIdentityResolver
from kh_agent.repository.metadata import MetadataInspector
from kh_agent.repository.safe_git import TargetSnapshot
from kh_agent.repository.snapshot import SourceScanner
from kh_agent.store.database import Database
from kh_agent.store.graphs import GraphStore
from kh_agent.store.registry import Registry

TargetInspector = Callable[[RepositoryIdentity, str], TargetSnapshot]
MUTATION_COMMANDS = ("modify", "optimize")


class Application:
    def __init__(
        self,
        db: Database,
        identities: IdentityService | None = None,
        resolver: RepositoryIdentityResolver | None = None,
        inspector: MetadataInspector | None = None,
        scanner: SourceScanner | None = None,
        risk_policy: RiskPolicy | None = None,
        target_inspector: TargetInspector | None = None,
    ) -> None:
        self.db = db
        self.identities = identities or IdentityService(db)
        self.resolver = resolver or RepositoryIdentityResolver()
        self.inspector = inspector or MetadataInspector()
        self.registry = Registry(db)
        self.authorization = AuthorizationService(db)
        self.scanner = scanner or SourceScanner()
        self.risk_policy = risk_policy
        # Without a Safe Git inspector, status stays metadata-only and mutation stays unavailable.
        self.target_inspector = target_inspector

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
            result = {"repository_id": repository_id, **self.inspector.inspect(current)}
            return {**result, **self._target_status(current, repository_id)}
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
        if command in MUTATION_COMMANDS and self.target_inspector is not None:
            current = self.resolver.resolve(path)
            if current != repository:
                raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
            # An unsafe target refuses mutation before capability availability is considered.
            require_mutation_target(self.target_inspector(current, repository_id))
        raise DomainError(
            ErrorCode.CAPABILITY_NOT_AVAILABLE,
            "This command requires analysis, sandbox or apply components not yet enabled",
        )

    def _target_status(self, identity: RepositoryIdentity, repository_id: str) -> dict:
        if self.target_inspector is None:
            return {}
        try:
            target = self.target_inspector(identity, repository_id)
        except DomainError as exc:
            # Status is read-only: report why, and never claim readiness that was not inspected.
            return {"target_inspection_error": exc.code.value, "mutation_ready": False}
        head, worktree = target.evidence["head"], target.evidence["worktree"]
        return {
            "inspection_scope": "SAFE_GIT_PLUMBING",
            "head_state": head["head_state"],
            "branch": head["branch"],
            "commit_sha": target.target_version,
            "working_tree_dirty": worktree["dirty"],
            "working_tree_diff_hash": worktree["working_tree_diff_hash"],
            "staged_changes": len(worktree["staged"]),
            "unstaged_changes": len(worktree["unstaged"]),
            "untracked_sources": len(worktree["untracked"]),
            "comparison_uncertain": len(worktree["comparison_uncertain"]),
            "object_source_authorization": target.evidence["object_state"][
                "object_source_authorization"
            ],
            "target_completeness": target.completeness,
            "target_state_digest": target.state_digest,
            "mutation_ready": target.mutation_ready,
        }
