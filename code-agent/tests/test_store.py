import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from kh_agent.access.gates import VerificationReadiness
from kh_agent.core.enums import CheckStatus, Classification, PatchState
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import RepositoryId
from kh_agent.core.lifecycle import CheckResult
from kh_agent.patch.canonical import ProposalBase, canonicalize_candidate
from kh_agent.store.database import Database, append_event
from kh_agent.store.patches import PatchStore


def canonical(env, intent, repository_id=None):
    base = ProposalBase(
        repository_id or env.repository_id,
        intent,
        "main",
        "a" * 40,
        "b" * 64,
        "c" * 64,
        "COMPLETE",
        False,
    )
    operations = [{"path": "a.py", "operation": "create", "content": "pass"}]
    return canonicalize_candidate(
        json.dumps({"operations": operations}).encode(),
        base,
        {},
        generator_provenance="test-generator-v1",
    )


def proposal(env, key="proposal", **kwargs):
    intent = env.patches.create_intent(
        env.repository_id,
        env.actor.user_id,
        "secret request must not be logged",
        "modify",
        "intent",
    )
    return env.patches.propose(
        user_id=env.actor.user_id,
        proposal=canonical(env, intent),
        classification=Classification.NORMAL,
        key=key,
        **kwargs,
    )


def verifying(env):
    patch = proposal(env)
    env.patches.record_worktree_result(
        patch["patch_id"], 1, env.actor.user_id, succeeded=True, key="worktree"
    )
    env.patches.begin_verification(
        patch["patch_id"],
        1,
        env.actor.user_id,
        readiness=VerificationReadiness(
            PatchState.APPLIED_TO_WORKTREE, True, "ALLOW", "risk", "plan"
        ),
        final_diff_hash="c" * 64,
        plan={"test": True, "optional": False},
        key="begin",
    )
    return patch


def finish(env, patch, key="finish", **kwargs):
    checks = kwargs.pop(
        "checks",
        (
            CheckResult("test", CheckStatus.PASS, True, "d" * 64),
            CheckResult("optional", CheckStatus.NOT_AVAILABLE, False, ""),
        ),
    )
    basis = dict.fromkeys(
        (
            "risk",
            "guardrail",
            "command",
            "sandbox",
            "security",
            "acceptance_mapping",
            "toolchain",
            "source_before",
            "source_after",
        ),
        "v1",
    )
    basis.update(kwargs.pop("basis", {}))
    return env.patches.finish_verification(
        patch["patch_id"], 1, env.actor.user_id, checks=checks, policy_basis=basis, key=key
    )


def test_wal_full_foreign_keys_and_future_schema(environment, tmp_path):
    db = environment.db
    assert db.rows("PRAGMA journal_mode")[0][0] == "wal"
    assert db.rows("PRAGMA synchronous")[0][0] == 2
    assert db.rows("PRAGMA foreign_keys")[0][0] == 1
    future = tmp_path / "future.db"
    conn = sqlite3.connect(future)
    conn.execute("PRAGMA user_version=100")
    conn.close()
    future.chmod(0o600)
    with pytest.raises(DomainError) as error:
        Database(future)
    assert error.value.code == ErrorCode.SCHEMA_VERSION_UNSUPPORTED


def test_append_only_audit(environment):
    for sql in ("DELETE FROM audit_events", "UPDATE audit_events SET event_type='fake'"):
        with pytest.raises(DomainError):
            with environment.db.transaction() as conn:
                conn.execute(sql)
    assert len(environment.db.rows("SELECT * FROM audit_events")) == 2


def test_audit_rejects_raw_source_and_credentials(environment):
    with pytest.raises(DomainError):
        with environment.db.transaction() as conn:
            append_event(
                conn,
                event_type="REQUEST_RECEIVED",
                aggregate_type="request",
                aggregate_id="request",
                repository_id=None,
                user_id=None,
                payload={"credential": "sensitive"},
            )


def test_proposal_retry_and_intent_binding(environment):
    env = environment
    first = proposal(env)
    assert proposal(env) == first
    second = proposal(env, key="revision-two", patch_id=first["patch_id"])
    assert second["revision"] == 2
    assert len(env.db.rows("SELECT * FROM patch_revisions")) == 2
    other = env.patches.create_intent(
        env.repository_id, env.actor.user_id, "other", "modify", "other"
    )
    with pytest.raises(DomainError):
        env.patches.propose(
            user_id=env.actor.user_id,
            proposal=canonical(env, other),
            key="bad",
            classification=Classification.NORMAL,
            patch_id=first["patch_id"],
        )
    assert "secret request" not in str(
        [tuple(r) for r in env.db.rows("SELECT * FROM audit_events")]
    )
    assert env.patches.check_integrity()["revisions_checked"] == 2


def test_proposal_base_must_be_canonical_and_match_intent_repository(environment):
    env = environment
    intent = env.patches.create_intent(
        env.repository_id, env.actor.user_id, "change", "modify", "intent"
    )
    for key, candidate in (
        ("other-repository", canonical(env, intent, str(RepositoryId.new()))),
        ("raw-payload", canonical(env, intent).payload()),
    ):
        with pytest.raises(DomainError) as error:
            env.patches.propose(
                user_id=env.actor.user_id,
                proposal=candidate,
                key=key,
                classification=Classification.NORMAL,
            )
        assert error.value.code == ErrorCode.INVALID_INPUT
    assert env.db.rows("SELECT * FROM patches") == []


def test_idempotency_conflict_is_not_silent(environment):
    proposal(environment)
    with pytest.raises(DomainError) as error:
        environment.patches.create_intent(
            environment.repository_id,
            environment.actor.user_id,
            "different request",
            "modify",
            "intent",
        )
    assert error.value.code == ErrorCode.IDEMPOTENCY_CONFLICT


def test_state_and_audit_roll_back_together(environment):
    env = environment
    patch = proposal(env)
    with env.db.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER simulate_disk_failure BEFORE INSERT ON audit_events "
            "WHEN NEW.event_type='PATCH_STATE_CHANGED' BEGIN "
            "SELECT RAISE(ABORT, 'injected I/O failure'); END"
        )
    with pytest.raises(DomainError) as error:
        env.patches.record_worktree_result(
            patch["patch_id"], 1, env.actor.user_id, succeeded=True, key="failure"
        )
    assert error.value.code == ErrorCode.CRITICAL_PERSISTENCE_FAILED
    assert env.db.rows("SELECT lifecycle_state FROM patch_revisions")[0][0] == "PROPOSED"
    assert not env.db.rows("SELECT * FROM operations WHERE idempotency_key='failure'")


def test_verification_persists_result_basis_state_and_replays(environment):
    env = environment
    patch = verifying(env)
    result = finish(env, patch)
    assert result["state"] == "VERIFIED"
    assert finish(env, patch) == result
    assert len(env.db.rows("SELECT * FROM verification_results")) == 1
    assert env.patches.check_integrity() == {"revisions_checked": 1}
    # Reopen a separate connection to the same durable SQLite state.
    path = env.db.rows("PRAGMA database_list")[0][2]
    from pathlib import Path

    reopened = Database(Path(path))
    try:
        assert PatchStore(reopened, env.artifacts).check_integrity() == {"revisions_checked": 1}
    finally:
        reopened.close()


def test_result_write_failure_does_not_publish_verified(environment):
    env = environment
    patch = verifying(env)
    with env.db.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER fail_basis BEFORE INSERT ON audit_events "
            "WHEN NEW.event_type='VERIFICATION_BASIS_RECORDED' BEGIN "
            "SELECT RAISE(ABORT, 'failure'); END"
        )
    with pytest.raises(DomainError):
        finish(env, patch)
    assert not env.db.rows("SELECT * FROM verification_results")
    row = env.db.rows("SELECT * FROM patch_revisions")[0]
    assert row["lifecycle_state"] == "VERIFYING"
    assert row["verification_result_id"] is None


def test_missing_required_check_cannot_be_removed_from_result(environment):
    patch = verifying(environment)
    with pytest.raises(DomainError) as error:
        finish(
            environment, patch, checks=(CheckResult("optional", CheckStatus.PASS, False, "a" * 64),)
        )
    assert error.value.code == ErrorCode.VERIFICATION_BASIS_MISMATCH


def test_source_mutation_produces_inconclusive(environment):
    result = finish(environment, verifying(environment), basis={"source_after": "changed"})
    assert result["state"] == "INCONCLUSIVE"


def test_artifact_tampering_prevents_verified(environment):
    env = environment
    patch = verifying(env)
    artifact_id = env.db.rows("SELECT artifact_id FROM artifacts")[0][0]
    env.artifacts.data[artifact_id] = b"tampered"
    with pytest.raises(DomainError) as error:
        finish(env, patch)
    assert error.value.code == ErrorCode.CRITICAL_PERSISTENCE_FAILED
    assert env.db.rows("SELECT lifecycle_state FROM patch_revisions")[0][0] == "VERIFYING"


def test_reconciliation_detects_event_state_divergence(environment):
    proposal(environment)
    with environment.db.transaction() as conn:
        conn.execute("UPDATE patch_revisions SET lifecycle_state='APPROVED'")
    with pytest.raises(DomainError):
        environment.patches.check_integrity()


def test_concurrent_retry_commits_one_result(environment):
    env = environment
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: proposal(env), range(8)))
    assert all(result == results[0] for result in results)
    assert len(env.db.rows("SELECT * FROM patch_revisions")) == 1


def test_history_is_metadata_only(environment):
    proposal(environment)
    events = environment.db.rows("SELECT payload_json FROM audit_events")
    assert all("request" not in json.loads(event[0]) for event in events)
