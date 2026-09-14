import hashlib
import json
from dataclasses import asdict
from typing import Any

from kh_agent.access.gates import VerificationReadiness
from kh_agent.core.canonical import ContentHash, canonical_bytes, canonical_hash
from kh_agent.core.clock import utc_now
from kh_agent.core.enums import Classification, PatchState
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import (
    PatchId,
    PatchRevision,
    RequestIntentId,
    VerificationBasisId,
    VerificationResultId,
)
from kh_agent.core.lifecycle import CheckResult, require_transition, verification_outcome
from kh_agent.store.artifacts import Artifact, ArtifactBackend
from kh_agent.store.database import Database, append_event


class PatchStore:
    """Persistence API for trusted orchestrators, not an untrusted RPC interface.

    It does not execute candidates, mark APPROVED/APPLIED, or grant authorization.
    Runtime proofs must originate in M05/M06/M07 before these persistence calls.
    """

    def __init__(self, db: Database, artifacts: ArtifactBackend) -> None:
        self.db = db
        self.artifacts = artifacts

    def create_intent(
        self, repository_id: str, user_id: str, request: str, request_type: str, key: str
    ) -> str:
        if request_type not in ("modify", "optimize") or not request.strip():
            raise DomainError(ErrorCode.INVALID_INPUT)
        request_hash = canonical_hash({"request": request}, "request-v1").digest

        def action(conn):
            intent_id = str(RequestIntentId.new())
            conn.execute(
                "INSERT INTO request_intents VALUES (?,?,?,?,?,?)",
                (intent_id, repository_id, user_id, request_hash, request_type, utc_now()),
            )
            append_event(
                conn,
                event_type="REQUEST_RECEIVED",
                aggregate_type="request_intent",
                aggregate_id=intent_id,
                repository_id=repository_id,
                user_id=user_id,
                payload={
                    "request_intent_id": intent_id,
                    "request_hash": request_hash,
                    "request_type": request_type,
                },
            )
            return {"request_intent_id": intent_id}

        return self.db.operation(
            key,
            {
                "action": "create_intent",
                "repository_id": repository_id,
                "user_id": user_id,
                "request_hash": request_hash,
                "request_type": request_type,
            },
            action,
        )["request_intent_id"]

    def propose(
        self,
        *,
        intent_id: str,
        user_id: str,
        base_commit: str,
        source_snapshot_hash: str,
        proposal: dict[str, Any],
        key: str,
        classification: Classification,
        patch_id: str | None = None,
    ) -> dict:
        if not isinstance(classification, Classification):
            raise DomainError(ErrorCode.INVALID_INPUT, "Trusted classification is required")
        ContentHash(source_snapshot_hash, "source-snapshot-v1")
        if len(base_commit) not in (40, 64) or any(
            c not in "0123456789abcdef" for c in base_commit
        ):
            raise DomainError(ErrorCode.INVALID_INPUT, "Resolvable base commit required")
        if patch_id is not None:
            PatchId(patch_id)
        # Caller supplies a canonical proposal from the trusted M05 adapter.
        # Candidate data is nested and cannot overwrite trusted request/base binding.
        request = {
            "action": "propose",
            "intent_id": intent_id,
            "user_id": user_id,
            "base_commit": base_commit,
            "source_snapshot_hash": source_snapshot_hash,
            "proposal": proposal,
            "patch_id": patch_id,
            "classification": classification.value,
        }

        def action(conn):
            intent = conn.execute(
                "SELECT * FROM request_intents WHERE request_intent_id=?", (intent_id,)
            ).fetchone()
            if not intent or intent["user_id"] != user_id:
                raise DomainError(ErrorCode.ACCESS_DENIED)
            current_patch_id = patch_id or str(PatchId.new())
            revision = 1
            if patch_id:
                patch = conn.execute(
                    "SELECT * FROM patches WHERE patch_id=?", (patch_id,)
                ).fetchone()
                if not patch or patch["request_intent_id"] != intent_id:
                    raise DomainError(ErrorCode.INVALID_INPUT, "Patch belongs to another intent")
                revision = conn.execute(
                    "SELECT MAX(revision)+1 FROM patch_revisions WHERE patch_id=?", (patch_id,)
                ).fetchone()[0]
            else:
                conn.execute(
                    "INSERT INTO patches VALUES (?,?,?)",
                    (current_patch_id, intent_id, intent["repository_id"]),
                )
            canonical = {
                "request_intent_id": intent_id,
                "repository_id": intent["repository_id"],
                "base_commit": base_commit,
                "source_snapshot_hash": source_snapshot_hash,
                "proposal": proposal,
            }
            data = canonical_bytes(canonical, "patch-proposal-v1")
            artifact = self.artifacts.write(data, "patch-proposal-v1", classification)
            # Durable file and integrity verification precede metadata/state commit.
            if self.artifacts.read(artifact) != data:
                raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
            conn.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)",
                (
                    artifact.artifact_id,
                    intent["repository_id"],
                    artifact.relative_path,
                    artifact.content_hash,
                    artifact.size,
                    artifact.classification,
                    artifact.schema_version,
                    utc_now(),
                ),
            )
            patch_hash = canonical_hash(canonical, "patch-proposal-v1").digest
            conn.execute(
                "INSERT INTO patch_revisions(patch_id,revision,patch_hash,artifact_id,"
                "proposal_base_commit,proposal_source_snapshot_hash,lifecycle_state) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    current_patch_id,
                    revision,
                    patch_hash,
                    artifact.artifact_id,
                    base_commit,
                    source_snapshot_hash,
                    PatchState.PROPOSED.value,
                ),
            )
            append_event(
                conn,
                event_type="PATCH_REVISION_CREATED",
                aggregate_type="patch",
                aggregate_id=current_patch_id,
                repository_id=intent["repository_id"],
                user_id=user_id,
                payload={
                    "revision": revision,
                    "patch_hash": patch_hash,
                    "request_intent_id": intent_id,
                    "artifact_id": artifact.artifact_id,
                },
            )
            return {"patch_id": current_patch_id, "revision": revision, "patch_hash": patch_hash}

        return self.db.operation(key, request, action)

    @staticmethod
    def _row(conn, patch_id: str, revision: int):
        PatchId(patch_id)
        PatchRevision(revision)
        row = conn.execute(
            "SELECT pr.*,p.repository_id,p.request_intent_id FROM patch_revisions pr "
            "JOIN patches p USING(patch_id) WHERE pr.patch_id=? AND pr.revision=?",
            (patch_id, revision),
        ).fetchone()
        if not row:
            raise DomainError(ErrorCode.INVALID_INPUT, "Unknown patch revision")
        return row

    @staticmethod
    def _transition(conn, row, target: PatchState, user_id: str, reason: str) -> None:
        require_transition(PatchState(row["lifecycle_state"]), target)
        conn.execute(
            "UPDATE patch_revisions SET lifecycle_state=? WHERE patch_id=? AND revision=?",
            (target.value, row["patch_id"], row["revision"]),
        )
        append_event(
            conn,
            event_type="PATCH_STATE_CHANGED",
            aggregate_type="patch",
            aggregate_id=row["patch_id"],
            repository_id=row["repository_id"],
            user_id=user_id,
            payload={
                "revision": row["revision"],
                "from": row["lifecycle_state"],
                "to": target.value,
                "reason_code": reason,
            },
        )

    def record_worktree_result(
        self, patch_id: str, revision: int, user_id: str, *, succeeded: bool, key: str
    ) -> dict:
        target = PatchState.APPLIED_TO_WORKTREE if succeeded else PatchState.PATCH_APPLY_FAILED

        def action(conn):
            row = self._row(conn, patch_id, revision)
            self._transition(conn, row, target, user_id, "WORKTREE_APPLY_RESULT")
            return {"state": target.value}

        return self.db.operation(
            key,
            {
                "action": "worktree_result",
                "patch_id": patch_id,
                "revision": revision,
                "user_id": user_id,
                "succeeded": succeeded,
            },
            action,
        )

    def begin_verification(
        self,
        patch_id: str,
        revision: int,
        user_id: str,
        *,
        readiness: VerificationReadiness,
        final_diff_hash: str,
        plan: dict[str, bool],
        key: str,
    ) -> dict:
        readiness.require()
        ContentHash(final_diff_hash, "change-set-v1")
        if (
            not plan
            or not all(type(v) is bool and k for k, v in plan.items())
            or not any(plan.values())
        ):
            raise DomainError(ErrorCode.INVALID_INPUT, "A required-check plan is mandatory")

        def action(conn):
            row = self._row(conn, patch_id, revision)
            if row["lifecycle_state"] != readiness.state:
                raise DomainError(ErrorCode.PATCH_NOT_READY_FOR_VERIFICATION)
            if row["final_diff_hash"] and row["final_diff_hash"] != final_diff_hash:
                raise DomainError(ErrorCode.VERIFICATION_BASIS_MISMATCH)
            self._transition(conn, row, PatchState.VERIFYING, user_id, "VERIFICATION_STARTED")
            conn.execute(
                "UPDATE patch_revisions SET final_diff_hash=?,verification_plan_json=? "
                "WHERE patch_id=? AND revision=?",
                (final_diff_hash, json.dumps(plan, sort_keys=True), patch_id, revision),
            )
            return {"state": PatchState.VERIFYING.value}

        return self.db.operation(
            key,
            {
                "action": "begin_verification",
                "patch_id": patch_id,
                "revision": revision,
                "user_id": user_id,
                "readiness": {**asdict(readiness), "state": readiness.state.value},
                "final_diff_hash": final_diff_hash,
                "plan": plan,
            },
            action,
        )

    def _artifact(self, conn, artifact_id: str) -> Artifact:
        row = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if not row:
            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
        return Artifact(**{key: row[key] for key in Artifact.__dataclass_fields__})

    def finish_verification(
        self,
        patch_id: str,
        revision: int,
        user_id: str,
        *,
        checks: tuple[CheckResult, ...],
        policy_basis: dict[str, str],
        key: str,
    ) -> dict:
        required_basis = {
            "risk",
            "guardrail",
            "command",
            "sandbox",
            "security",
            "acceptance_mapping",
            "toolchain",
            "source_before",
            "source_after",
        }
        if policy_basis.keys() != required_basis or not all(policy_basis.values()):
            raise DomainError(ErrorCode.VERIFICATION_BASIS_MISMATCH)
        check_data = [{**asdict(check), "status": check.status.value} for check in checks]

        def action(conn):
            row = self._row(conn, patch_id, revision)
            if row["lifecycle_state"] != PatchState.VERIFYING:
                raise DomainError(ErrorCode.INVALID_STATE_TRANSITION)
            plan = json.loads(row["verification_plan_json"])
            if {c.name: c.required for c in checks} != plan:
                raise DomainError(
                    ErrorCode.VERIFICATION_BASIS_MISMATCH,
                    "Checks do not match the persisted verification plan",
                )
            artifact = self._artifact(conn, row["artifact_id"])
            data = self.artifacts.read(artifact)
            if hashlib.sha256(data).hexdigest() != row["patch_hash"]:
                raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
            outcome = verification_outcome(checks)
            if policy_basis["source_before"] != policy_basis["source_after"]:
                outcome = PatchState.INCONCLUSIVE
            basis = {
                "patch_id": patch_id,
                "revision": revision,
                "patch_hash": row["patch_hash"],
                "final_diff_hash": row["final_diff_hash"],
                "request_intent_id": row["request_intent_id"],
                "policies": policy_basis,
                "plan": plan,
                "checks": check_data,
            }
            basis_hash = canonical_hash(basis, "verification-basis-v1").digest
            result_id, basis_id = str(VerificationResultId.new()), str(VerificationBasisId.new())
            conn.execute(
                "INSERT INTO verification_results VALUES (?,?,?,?,?,?,?,?)",
                (
                    result_id,
                    basis_id,
                    patch_id,
                    revision,
                    basis_hash,
                    json.dumps(basis, sort_keys=True),
                    json.dumps(check_data, sort_keys=True),
                    outcome.value,
                ),
            )
            conn.execute(
                "UPDATE patch_revisions SET verification_result_id=?,verification_basis_id=? "
                "WHERE patch_id=? AND revision=?",
                (result_id, basis_id, patch_id, revision),
            )
            append_event(
                conn,
                event_type="VERIFICATION_BASIS_RECORDED",
                aggregate_type="patch",
                aggregate_id=patch_id,
                repository_id=row["repository_id"],
                user_id=user_id,
                payload={
                    "revision": revision,
                    "verification_result_id": result_id,
                    "verification_basis_id": basis_id,
                    "basis_hash": basis_hash,
                },
            )
            self._transition(conn, row, outcome, user_id, "VERIFICATION_FINISHED")
            return {
                "state": outcome.value,
                "verification_result_id": result_id,
                "verification_basis_id": basis_id,
            }

        return self.db.operation(
            key,
            {
                "action": "finish_verification",
                "patch_id": patch_id,
                "revision": revision,
                "user_id": user_id,
                "checks": check_data,
                "policy_basis": policy_basis,
            },
            action,
        )

    def check_integrity(self) -> dict:
        """Read-only startup reconciliation: corruption never creates authority."""
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT * FROM patch_revisions").fetchall()
            for row in rows:
                state = PatchState.PROPOSED
                events = conn.execute(
                    "SELECT event_type,payload_json FROM audit_events "
                    "WHERE aggregate_type='patch' AND aggregate_id=? ORDER BY sequence",
                    (row["patch_id"],),
                ).fetchall()
                created = 0
                for event in events:
                    payload = json.loads(event["payload_json"])
                    if payload.get("revision") != row["revision"]:
                        continue
                    if event["event_type"] == "PATCH_REVISION_CREATED":
                        created += 1
                        if payload["patch_hash"] != row["patch_hash"]:
                            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                    if event["event_type"] == "PATCH_STATE_CHANGED":
                        if payload["from"] != state:
                            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                        target = PatchState(payload["to"])
                        require_transition(state, target)
                        state = target
                if created != 1 or state != row["lifecycle_state"]:
                    raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                self.artifacts.read(self._artifact(conn, row["artifact_id"]))
                if row["verification_result_id"]:
                    result = conn.execute(
                        "SELECT * FROM verification_results WHERE result_id=?",
                        (row["verification_result_id"],),
                    ).fetchone()
                    if (
                        not result
                        or result["basis_id"] != row["verification_basis_id"]
                        or canonical_hash(
                            json.loads(result["basis_json"]), "verification-basis-v1"
                        ).digest
                        != result["basis_hash"]
                    ):
                        raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                    basis = json.loads(result["basis_json"])
                    if (
                        result["patch_id"] != row["patch_id"]
                        or result["revision"] != row["revision"]
                        or basis["patch_id"] != row["patch_id"]
                        or basis["revision"] != row["revision"]
                        or basis["patch_hash"] != row["patch_hash"]
                        or basis["final_diff_hash"] != row["final_diff_hash"]
                        or basis["checks"] != json.loads(result["checks_json"])
                    ):
                        raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                    if state in (PatchState.VERIFIED, PatchState.APPROVED, PatchState.APPLIED):
                        if result["outcome"] != PatchState.VERIFIED:
                            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                elif state in (PatchState.VERIFIED, PatchState.APPROVED, PatchState.APPLIED):
                    raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
        return {"revisions_checked": len(rows)}
