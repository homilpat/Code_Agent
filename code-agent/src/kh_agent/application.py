import json
from collections.abc import Callable
from pathlib import Path

from kh_agent.access.gates import require_mutation_target
from kh_agent.access.service import AuthorizationService
from kh_agent.analysis.python_graph import build_graph, explain, impact
from kh_agent.analysis.risk import RiskPolicy, score_risk
from kh_agent.core.canonical import ContentHash, encode_path
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.identity.service import IdentityService
from kh_agent.patch.canonical import parse_candidate, target_path
from kh_agent.patch.local_model import LocalModelClient
from kh_agent.patch.preview import candidate_source_view, preview_candidate
from kh_agent.repository.identity import RepositoryIdentity, RepositoryIdentityResolver
from kh_agent.repository.metadata import MetadataInspector
from kh_agent.repository.safe_git import TargetSnapshot
from kh_agent.repository.snapshot import SourceScanner
from kh_agent.sandbox.container import RootlessContainerBackend
from kh_agent.sandbox.policy import IMAGE_REFERENCE, PytestRequest, compile_pytest
from kh_agent.store.database import Database
from kh_agent.store.graphs import GraphStore
from kh_agent.store.registry import Registry
from kh_agent.store.worktree_journal import WorktreeWriteJournal, journaled_replace_source_file

TargetInspector = Callable[[RepositoryIdentity, str], TargetSnapshot]
SandboxFactory = Callable[[str], RootlessContainerBackend]
ModelFactory = Callable[[str, int], LocalModelClient]
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
        sandbox_factory: SandboxFactory | None = None,
        model_factory: ModelFactory | None = None,
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
        self.sandbox_factory = sandbox_factory or RootlessContainerBackend
        self.model_factory = model_factory or LocalModelClient

    def generate_preview(
        self, path: Path, target: str, request: str, model: str, port: int = 1234
    ) -> dict:
        """Ask a loopback model for one candidate, then validate it as read-only data."""
        identity = self.identities.resolve()
        repository = self.resolver.resolve(path)
        repository_id = self.registry.lookup(repository)
        for command in ("modify", "explain"):
            self.authorization.authorize(identity, repository_id, command)
        if self.target_inspector is None:
            raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "Safe Git inspection unavailable")
        baseline = self.target_inspector(repository, repository_id)
        require_mutation_target(baseline)
        snapshot = self.scanner.scan(repository)
        target_bytes = target_path(target)
        source = next((item for item in snapshot.files if item.path == target_bytes), None)
        if source is None:
            raise DomainError(ErrorCode.INVALID_INPUT, "Target is not in the safe source view")
        candidate = self.model_factory(model, port).generate(request, target, source.content)
        result = preview_candidate(candidate, snapshot)
        if result["path"] != target:
            raise DomainError(ErrorCode.INVALID_INPUT, "Model changed an unauthorized target")
        if self.resolver.resolve(path) != repository:
            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
        if self.scanner.scan(repository).snapshot_hash != snapshot.snapshot_hash:
            raise DomainError(
                ErrorCode.REPOSITORY_STATE_BLOCKED, "Source changed during generation"
            )
        for command in ("modify", "explain"):
            self.authorization.authorize(identity, repository_id, command, "AFTER_SOURCE_INGESTION")
        latest = self.target_inspector(repository, repository_id)
        require_mutation_target(latest)
        if latest.state_digest != baseline.state_digest:
            raise DomainError(
                ErrorCode.REPOSITORY_STATE_BLOCKED, "Target changed during generation"
            )
        return {
            "repository_id": repository_id,
            "status": "MODEL_PREVIEW_ONLY",
            "apply_ready": False,
            "target_state_digest": latest.state_digest,
            "model": model,
            "candidate": parse_candidate(candidate),
            **{key: value for key, value in result.items() if key != "status"},
        }

    def generate_and_verify(
        self,
        path: Path,
        target: str,
        request: str,
        model: str,
        image: str,
        tests: tuple[str, ...],
        port: int = 1234,
    ) -> dict:
        """Generate one candidate and test its in-memory view without applying it."""
        identity = self.identities.resolve()
        repository = self.resolver.resolve(path)
        repository_id = self.registry.lookup(repository)
        commands = ("modify", "explain", "verify")
        for command in commands:
            self.authorization.authorize(identity, repository_id, command)
        if self.target_inspector is None:
            raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "Safe Git inspection unavailable")
        if not IMAGE_REFERENCE.fullmatch(image):
            raise DomainError(ErrorCode.INVALID_INPUT, "An immutable sandbox image is required")
        compiled = compile_pytest(PytestRequest(tests))
        baseline = self.target_inspector(repository, repository_id)
        require_mutation_target(baseline)
        snapshot = self.scanner.scan(repository)
        target_bytes = target_path(target)
        source = next((item for item in snapshot.files if item.path == target_bytes), None)
        if source is None:
            raise DomainError(ErrorCode.INVALID_INPUT, "Target is not in the safe source view")
        candidate = self.model_factory(model, port).generate(request, target, source.content)
        preview = preview_candidate(candidate, snapshot)
        if preview["path"] != target:
            raise DomainError(ErrorCode.INVALID_INPUT, "Model changed an unauthorized target")
        view = candidate_source_view(candidate, snapshot)

        def recheck(phase: str) -> TargetSnapshot:
            if self.resolver.resolve(path) != repository:
                raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
            if self.scanner.scan(repository).snapshot_hash != snapshot.snapshot_hash:
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, f"Source changed {phase}")
            for command in commands:
                self.authorization.authorize(
                    identity, repository_id, command, "AFTER_SOURCE_INGESTION"
                )
            latest = self.target_inspector(repository, repository_id)
            require_mutation_target(latest)
            if latest.state_digest != baseline.state_digest:
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, f"Target changed {phase}")
            return latest

        recheck("before test")
        result = self.sandbox_factory(image).execute(compiled, view)
        latest = recheck("during test")
        return {
            "repository_id": repository_id,
            "status": "MODEL_TEST_EXPERIMENTAL",
            "apply_ready": False,
            "model": model,
            "candidate": parse_candidate(candidate),
            **{key: value for key, value in preview.items() if key != "status"},
            "candidate_view_hash": view.snapshot_hash,
            "target_state_digest": latest.state_digest,
            "test_status": result.status,
            "exit_code": result.exit_code,
            "termination_reason": result.termination_reason,
            "output": result.output,
            "output_truncated": result.output_truncated,
            "output_sha256": result.output_sha256,
            "plan_hash": result.plan_hash,
            "attestation_digest": result.attestation_digest,
        }

    def preview(self, path: Path, candidate_file: Path) -> dict:
        """Inspect a supplied candidate without persisting or modifying repository files."""
        identity = self.identities.resolve()
        repository = self.resolver.resolve(path)
        repository_id = self.registry.lookup(repository)
        self.authorization.authorize(identity, repository_id, "modify")
        # The diff reveals source text, so proposal permission alone is insufficient.
        self.authorization.authorize(identity, repository_id, "explain")
        if self.target_inspector is None:
            raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "Safe Git inspection unavailable")
        baseline = self.target_inspector(repository, repository_id)
        require_mutation_target(baseline)
        snapshot = self.scanner.scan(repository)
        with candidate_file.open("rb") as stream:
            candidate = stream.read(1024 * 1024 + 1)
        result = preview_candidate(candidate, snapshot)
        if self.resolver.resolve(path) != repository:
            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
        if self.scanner.scan(repository).snapshot_hash != snapshot.snapshot_hash:
            raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Source changed during preview")
        self.authorization.authorize(identity, repository_id, "modify", "AFTER_SOURCE_INGESTION")
        self.authorization.authorize(identity, repository_id, "explain", "AFTER_SOURCE_INGESTION")
        latest = self.target_inspector(repository, repository_id)
        require_mutation_target(latest)
        if latest.state_digest != baseline.state_digest:
            raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Target changed during preview")
        return {
            "repository_id": repository_id,
            "target_state_digest": latest.state_digest,
            **result,
        }

    def verify_candidate(
        self,
        path: Path,
        candidate_file: Path,
        image: str,
        tests: tuple[str, ...],
    ) -> dict:
        """Run registered pytest on an ephemeral candidate view; never grant apply authority."""
        identity = self.identities.resolve()
        repository = self.resolver.resolve(path)
        repository_id = self.registry.lookup(repository)
        for command in ("modify", "explain", "verify"):
            self.authorization.authorize(identity, repository_id, command)
        if self.target_inspector is None:
            raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "Safe Git inspection unavailable")
        if not IMAGE_REFERENCE.fullmatch(image):
            raise DomainError(ErrorCode.INVALID_INPUT, "An immutable sandbox image is required")
        compiled = compile_pytest(PytestRequest(tests))
        baseline = self.target_inspector(repository, repository_id)
        require_mutation_target(baseline)
        snapshot = self.scanner.scan(repository)
        with candidate_file.open("rb") as stream:
            candidate = stream.read(1024 * 1024 + 1)
        preview = preview_candidate(candidate, snapshot)
        view = candidate_source_view(candidate, snapshot)
        if self.resolver.resolve(path) != repository:
            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
        if self.scanner.scan(repository).snapshot_hash != snapshot.snapshot_hash:
            raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Source changed before test")
        if self.target_inspector(repository, repository_id).state_digest != baseline.state_digest:
            raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Target changed before test")
        for command in ("modify", "explain", "verify"):
            self.authorization.authorize(identity, repository_id, command, "AFTER_SOURCE_INGESTION")
        result = self.sandbox_factory(image).execute(compiled, view)
        # The reported result must still refer to the source and rights originally checked.
        if self.resolver.resolve(path) != repository:
            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
        if self.scanner.scan(repository).snapshot_hash != snapshot.snapshot_hash:
            raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Source changed during test")
        for command in ("modify", "explain", "verify"):
            self.authorization.authorize(identity, repository_id, command, "AFTER_SOURCE_INGESTION")
        latest = self.target_inspector(repository, repository_id)
        require_mutation_target(latest)
        if latest.state_digest != baseline.state_digest:
            raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Target changed during test")
        return {
            "repository_id": repository_id,
            "status": "EXPERIMENTAL_TEST_ONLY",
            "apply_ready": False,
            "candidate_hash": preview["candidate_hash"],
            "source_snapshot_hash": snapshot.snapshot_hash,
            "candidate_view_hash": view.snapshot_hash,
            "source_completeness": snapshot.completeness,
            "target_state_digest": latest.state_digest,
            "test_status": result.status,
            "exit_code": result.exit_code,
            "termination_reason": result.termination_reason,
            "output": result.output,
            "output_truncated": result.output_truncated,
            "output_sha256": result.output_sha256,
            "plan_hash": result.plan_hash,
            "attestation_digest": result.attestation_digest,
        }

    def apply_tested_candidate(
        self,
        path: Path,
        candidate_file: Path,
        reviewed_hash: str,
        reviewed_source_hash: str,
        reviewed_target_digest: str,
        image: str,
        tests: tuple[str, ...],
    ) -> dict:
        """Explicit experimental one-file apply; never claim formal patch verification."""
        identity = self.identities.resolve()
        repository = self.resolver.resolve(path)
        repository_id = self.registry.lookup(repository)
        commands = ("modify", "explain", "verify", "apply")
        for command in commands:
            self.authorization.authorize(identity, repository_id, command)
        try:
            for digest in (reviewed_hash, reviewed_source_hash, reviewed_target_digest):
                ContentHash(digest, "review-binding-v1")
        except ValueError as exc:
            raise DomainError(ErrorCode.INVALID_INPUT, "Reviewed candidate hash required") from exc
        if self.target_inspector is None:
            raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "Safe Git inspection unavailable")
        if not IMAGE_REFERENCE.fullmatch(image):
            raise DomainError(ErrorCode.INVALID_INPUT, "An immutable sandbox image is required")
        compiled = compile_pytest(PytestRequest(tests))
        journal = WorktreeWriteJournal(self.db)
        if journal.pending(repository_id):
            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED, "Unresolved worktree write")
        baseline = self.target_inspector(repository, repository_id)
        require_mutation_target(baseline)
        snapshot = self.scanner.scan(repository)
        if (
            baseline.state_digest != reviewed_target_digest
            or snapshot.snapshot_hash != reviewed_source_hash
        ):
            raise DomainError(ErrorCode.VERIFICATION_BASIS_MISMATCH, "Reviewed base changed")
        with candidate_file.open("rb") as stream:
            candidate = stream.read(1024 * 1024 + 1)
        preview = preview_candidate(candidate, snapshot)
        if preview["candidate_hash"] != reviewed_hash:
            raise DomainError(ErrorCode.VERIFICATION_BASIS_MISMATCH, "Candidate was not reviewed")
        view = candidate_source_view(candidate, snapshot)
        source = next(item for item in snapshot.files if item.path == target_path(preview["path"]))
        replacement = parse_candidate(candidate)["operations"][0]["content"].encode("utf-8")

        def recheck(phase: str) -> None:
            if self.resolver.resolve(path) != repository:
                raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
            if self.scanner.scan(repository).snapshot_hash != snapshot.snapshot_hash:
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, f"Source changed {phase}")
            for command in commands:
                self.authorization.authorize(
                    identity, repository_id, command, "AFTER_SOURCE_INGESTION"
                )
            latest = self.target_inspector(repository, repository_id)
            require_mutation_target(latest)
            if latest.state_digest != baseline.state_digest:
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, f"Target changed {phase}")

        recheck("before test")
        test_result = self.sandbox_factory(image).execute(compiled, view)
        recheck("during test")
        if (
            test_result.status != "PASS"
            or test_result.exit_code != 0
            or test_result.termination_reason != "EXITED"
            or test_result.output_truncated
        ):
            raise DomainError(ErrorCode.PATCH_NOT_VERIFIED, "Candidate pytest did not pass")
        for proof in (test_result.plan_hash, test_result.attestation_digest):
            try:
                ContentHash(proof, "sandbox-proof-v1")
            except ValueError as exc:
                raise DomainError(ErrorCode.PATCH_NOT_VERIFIED, "Sandbox proof is missing") from exc

        def postcommit() -> None:
            if self.resolver.resolve(path) != repository:
                raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
            actual = self.scanner.scan(repository)
            if (
                actual.exclusions != snapshot.exclusions
                or [(item.path, item.content_hash) for item in actual.files]
                != [(item.path, item.content_hash) for item in view.files]
            ):
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Source changed after apply")
            changed = self.target_inspector(repository, repository_id)
            worktree = changed.evidence["worktree"]
            if (
                changed.target_id != baseline.target_id
                or changed.target_version != baseline.target_version
                or changed.completeness != "COMPLETE"
                or changed.evidence["head"] != baseline.evidence["head"]
                or changed.evidence["object_state"] != baseline.evidence["object_state"]
                or changed.evidence["ingestion_policy_hash"]
                != baseline.evidence["ingestion_policy_hash"]
                or changed.evidence["git_operations"]
                or worktree["staged"]
                or worktree["untracked"]
                or worktree["comparison_uncertain"]
            ):
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Unexpected Git change")
            if (
                len(worktree["unstaged"]) != 1
                or worktree["unstaged"][0]["path"] != encode_path(source.path)
                or worktree["unstaged"][0]["kind"] != "MODIFIED"
            ):
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Unexpected Git change")

        digest = journaled_replace_source_file(
            journal, repository_id, identity.user_id, repository, source, replacement,
            source_snapshot_hash=snapshot.snapshot_hash,
            target_state_digest=baseline.state_digest,
            precommit=lambda: recheck("before apply"),
            postcommit=postcommit,
            candidate_hash=reviewed_hash,
            test_plan_hash=test_result.plan_hash,
            test_attestation_digest=test_result.attestation_digest,
        )
        return {
            "repository_id": repository_id,
            "status": "EXPERIMENTAL_APPLIED",
            "formal_verification": False,
            "candidate_hash": reviewed_hash,
            "source_completeness": snapshot.completeness,
            "target_state_digest_before": baseline.state_digest,
            "path": preview["path"],
            "after_sha256": digest,
            "test_status": test_result.status,
            "plan_hash": test_result.plan_hash,
            "attestation_digest": test_result.attestation_digest,
        }

    def reconcile_write(self, path: Path, attempt_id: str, target: str) -> dict:
        """Record observed on-disk bytes for a pending write; no automatic retry."""
        identity = self.identities.resolve()
        repository = self.resolver.resolve(path)
        repository_id = self.registry.lookup(repository)
        self.authorization.authorize(identity, repository_id, "apply")
        raw = target_path(target)
        if not raw.endswith(b".py"):
            raise DomainError(ErrorCode.INVALID_INPUT, "Pending target must be a Python file")
        reason = WorktreeWriteJournal(self.db).reconcile(
            repository_id, identity.user_id, attempt_id, repository, raw
        )
        return {
            "repository_id": repository_id,
            "status": "WRITE_RECONCILED",
            "observed": reason,
            "apply_ready": False,
            "attempt_id": attempt_id,
        }

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
            baseline = self.target_inspector(current, repository_id)
            require_mutation_target(baseline)
            latest = self.target_inspector(current, repository_id)
            require_mutation_target(latest)
            if latest.state_digest != baseline.state_digest:
                raise DomainError(
                    ErrorCode.REPOSITORY_STATE_BLOCKED, "Target changed during inspection"
                )
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
        pending = WorktreeWriteJournal(self.db).pending(repository_id)
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
            "mutation_ready": target.mutation_ready and not pending,
            "unresolved_worktree_writes": len(pending),
            "unresolved_write_attempts": pending,
        }
