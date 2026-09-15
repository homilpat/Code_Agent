import pytest

from kh_agent.access.gates import (
    MutationContext,
    VerificationReadiness,
    require_normal_mutation,
    select_revision,
)
from kh_agent.cli.renderer import render
from kh_agent.core.canonical import canonical_bytes, canonical_hash, decode_path, encode_path
from kh_agent.core.enums import CheckStatus, PatchState
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import PatchId, PatchRevision, RepositoryId
from kh_agent.core.lifecycle import CheckResult, require_transition, verification_outcome


def test_typed_ids_cannot_be_confused():
    patch = PatchId.new()
    assert PatchId(str(patch)) == patch
    with pytest.raises(ValueError):
        RepositoryId(str(patch))
    for value in (0, -1, True, 1.5, "1"):
        with pytest.raises(ValueError):
            PatchRevision(value)


def test_hash_order_schema_and_unicode_identity():
    assert canonical_hash({"b": 1, "a": None}, "v1") == canonical_hash({"a": None, "b": 1}, "v1")
    assert canonical_hash({"a": 1}, "v1") != canonical_hash({"a": 1}, "v2")
    assert canonical_hash("é", "v1") != canonical_hash("e\u0301", "v1")
    assert canonical_bytes({"a": 1}, "v1") == (
        b'{"canonical_version":"kh-json-v1","schema_version":"v1","value":{"a":1}}'
    )


@pytest.mark.parametrize(
    "value", [1.2, float("nan"), float("inf"), {1: "a"}, b"bytes", (1, 2), 2**63, "\ud800"]
)
def test_ambiguous_serialization_rejected(value):
    with pytest.raises((ValueError, UnicodeError)):
        canonical_bytes(value, "v1")


@pytest.mark.req("M02-PRS-005", partial=True)
def test_filesystem_path_bytes_are_reversible():
    raw = b"src/\xff\xfe\n.py"
    assert decode_path(encode_path(raw)) == raw
    assert encode_path(b"A") != encode_path(b"a")
    for path in (b"../secret", b"/tmp/file", b"a/../b", b"a//b", b"a\0b"):
        with pytest.raises(DomainError):
            encode_path(path)
    with pytest.raises(DomainError):
        decode_path("$$invalid")


@pytest.mark.req("M01-SEC-001", "M01-SEC-002", "M01-SEC-004")
@pytest.mark.req("M01-SEC-003", partial=True)
def test_terminal_controls_never_reach_display():
    value = render({"path": "x\x1b]52;c;evil\x07\u202e\u009b\n[bold]"})
    assert "\x1b" not in value and "\x07" not in value and "\u202e" not in value
    assert "\\u001b" in value and "\\u202e" in value


@pytest.mark.parametrize(
    "state",
    [
        PatchState.PROPOSED,
        PatchState.PATCH_APPLY_FAILED,
        PatchState.FAILED,
        PatchState.INCONCLUSIVE,
    ],
)
@pytest.mark.req("M01-IT-015", partial=True)
def test_cannot_skip_verification_to_approval(state):
    with pytest.raises(DomainError):
        require_transition(state, PatchState.APPROVED)


def test_required_verification_unknown_never_passes():
    assert verification_outcome(()) == PatchState.INCONCLUSIVE
    for status in (
        CheckStatus.NOT_AVAILABLE,
        CheckStatus.INCONCLUSIVE,
        CheckStatus.NOT_APPLICABLE,
        CheckStatus.ERROR,
    ):
        assert (
            verification_outcome((CheckResult("test", status, True, "a" * 64),))
            == PatchState.INCONCLUSIVE
        )
    assert (
        verification_outcome((CheckResult("test", CheckStatus.PASS, True, ""),))
        == PatchState.INCONCLUSIVE
    )
    assert (
        verification_outcome((CheckResult("test", CheckStatus.FAIL, True, "a" * 64),))
        == PatchState.FAILED
    )
    checks = (
        CheckResult("test", CheckStatus.PASS, True, "a" * 64),
        CheckResult("optional", CheckStatus.INCONCLUSIVE, False, ""),
        CheckResult("optional-error", CheckStatus.ERROR, False, ""),
        CheckResult("optional-na", CheckStatus.NOT_APPLICABLE, False, ""),
    )
    assert verification_outcome(checks) == PatchState.VERIFIED


def test_required_check_cannot_exempt_itself_as_not_applicable():
    # No caller-supplied reference field exists any more to justify the exemption.
    assert "na_decision_reference" not in CheckResult.__dataclass_fields__
    checks = (
        CheckResult("lint", CheckStatus.PASS, True, "a" * 64),
        CheckResult("test", CheckStatus.NOT_APPLICABLE, True, "b" * 64),
    )
    assert verification_outcome(checks) == PatchState.INCONCLUSIVE


@pytest.mark.req("M01-UT-006")
def test_ambiguous_selector_never_selects_latest():
    with pytest.raises(DomainError) as error:
        select_revision([("p", 1), ("p", 2)])
    assert error.value.code == ErrorCode.AMBIGUOUS_PATCH_SELECTION
    assert select_revision([("p", 1), ("p", 2)], "p", 1) == ("p", 1)
    with pytest.raises(DomainError):
        select_revision([("p", 1)], revision=1)


@pytest.mark.req("M01-UT-005")
def test_omitted_selector_picks_the_only_eligible_revision():
    assert select_revision([("p", 1)]) == ("p", 1)
    assert select_revision([("p", 1), ("q", 2)], "q") == ("q", 2)


@pytest.mark.parametrize(
    "context",
    [
        MutationContext("DETACHED", None, "a", "NORMAL", False),
        MutationContext("UNBORN", "main", None, "NORMAL", False),
        MutationContext("NORMAL", "main", "a", "REBASE", False),
        MutationContext("NORMAL", "main", "a", "NORMAL", None),
        MutationContext("NORMAL", "main", "a", "NORMAL", True),
    ],
)
@pytest.mark.req("M01-IT-007", "M01-IT-008", "M01-IT-009", partial=True)
def test_mutation_gate_unknown_and_dirty_blocked(context):
    with pytest.raises(DomainError):
        require_normal_mutation(context)


def test_mutation_target_requires_a_ready_safe_git_snapshot():
    from dataclasses import replace

    from kh_agent.access.gates import require_mutation_target
    from kh_agent.repository.safe_git import TargetSnapshot

    evidence = {
        "head": {"head_state": "NORMAL", "branch": "main", "commit_sha": "a" * 40},
        "git_operations": [],
        "worktree": {"dirty": False},
    }
    ready = TargetSnapshot(
        "repo", "GIT_WORKTREE", "a" * 40, "d" * 64, "WORKTREE", "t", "m", "COMPLETE", True, evidence
    )
    require_mutation_target(ready)
    for changed, code in (
        ({"evidence": {**evidence, "worktree": {"dirty": True}}}, ErrorCode.DIRTY_WORKTREE_BLOCKED),
        ({"evidence": {**evidence, "git_operations": ["MERGE_HEAD"]}}, None),
        ({"completeness": "PARTIAL"}, None),
    ):
        with pytest.raises(DomainError) as error:
            require_mutation_target(replace(ready, mutation_ready=False, **changed))
        assert error.value.code == (code or ErrorCode.REPOSITORY_STATE_BLOCKED)


@pytest.mark.req("M01-IT-012", "M01-IT-013", "M01-IT-014", partial=True)
def test_verification_gate_requires_all_prerequisites():
    good = dict(
        state=PatchState.APPLIED_TO_WORKTREE,
        change_set_complete=True,
        post_apply_guardrail="ALLOW",
        final_risk_reference="risk",
        verification_plan_reference="plan",
    )
    VerificationReadiness(**good).require()
    for key, bad in (
        ("state", PatchState.PROPOSED),
        ("change_set_complete", False),
        ("post_apply_guardrail", "DENY"),
        ("final_risk_reference", None),
        ("verification_plan_reference", None),
    ):
        with pytest.raises(DomainError):
            VerificationReadiness(**{**good, key: bad}).require()
