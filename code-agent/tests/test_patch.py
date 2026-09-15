import json
from dataclasses import replace

import pytest

from kh_agent.core.enums import Classification
from kh_agent.core.errors import DomainError
from kh_agent.core.ids import RepositoryId, RequestIntentId
from kh_agent.patch.canonical import (
    BaselineFile,
    ProposalBase,
    actual_change_set,
    canonicalize_candidate,
    parse_candidate,
    require_manifest_match,
    require_same_base,
    simulate,
)


@pytest.fixture
def base():
    return ProposalBase(
        str(RepositoryId.new()),
        str(RequestIntentId.new()),
        "main",
        "a" * 40,
        "b" * 64,
        "c" * 64,
        "COMPLETE",
        False,
    )


def candidate(base, baseline, operations):
    return canonicalize_candidate(
        json.dumps({"operations": operations}).encode(),
        base,
        baseline,
        generator_provenance="test-generator-v1",
    )


def test_create_modify_delete_preview_preserves_original(base):
    baseline = {b"a.py": BaselineFile(b"old"), b"b.py": BaselineFile(b"delete", 0o755)}
    patch = candidate(
        base,
        baseline,
        [
            {"path": "a.py", "operation": "modify", "content": "new"},
            {"path": "b.py", "operation": "delete"},
            {"path": "c.py", "operation": "create", "content": "added"},
        ],
    )
    result = simulate(patch, baseline)
    assert baseline[b"a.py"].content == b"old" and b"b.py" in baseline
    assert result == {b"a.py": BaselineFile(b"new"), b"c.py": BaselineFile(b"added")}
    require_manifest_match(patch, actual_change_set(baseline, result))


def test_candidate_cannot_overwrite_authority_fields(base):
    for key in ("repository_id", "request_intent_id", "patch_hash", "policy", "approval"):
        with pytest.raises(DomainError):
            canonicalize_candidate(
                json.dumps({"operations": [], key: "forged"}).encode(),
                base,
                {},
                generator_provenance="test",
            )
    for data in (b'{"operations":[],"operations":[]}', b'{"operations": NaN}', b"[]", b"null"):
        with pytest.raises(DomainError):
            parse_candidate(data)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/abs.py",
        "a/../b.py",
        "a//b.py",
        ".git/config",
        "a/.GIT/hooks",
        "C:/file.py",
        "a\\b.py",
    ],
)
def test_unsafe_targets_blocked(base, path):
    with pytest.raises(DomainError):
        candidate(base, {}, [{"path": path, "operation": "create", "content": "pass"}])


def test_alias_duplicate_and_parent_file_conflicts_blocked(base):
    for operations, baseline in (
        (
            [
                {"path": "a.py", "operation": "create", "content": "1"},
                {"path": "A.py", "operation": "create", "content": "2"},
            ],
            {},
        ),
        ([{"path": "a", "operation": "create", "content": "1"}], {b"a/b.py": BaselineFile(b"2")}),
        ([{"path": "a/b.py", "operation": "create", "content": "1"}], {b"a": BaselineFile(b"2")}),
    ):
        with pytest.raises(DomainError):
            candidate(base, baseline, operations)


@pytest.mark.parametrize(
    "operation,baseline",
    [
        ({"path": "a", "operation": "rename", "content": "x"}, {}),
        ({"path": "a", "operation": "symlink", "content": "/etc/passwd"}, {}),
        ({"path": "a", "operation": "modify", "content": "x"}, {}),
        ({"path": "a", "operation": "create", "content": "x"}, {b"a": BaselineFile(b"old")}),
        (
            {"path": "a", "operation": "delete", "content": "unexpected"},
            {b"a": BaselineFile(b"old")},
        ),
    ],
)
def test_unsupported_and_ambiguous_operations_blocked(base, operation, baseline):
    with pytest.raises(DomainError):
        candidate(base, baseline, [operation])


def test_sensitive_change_blocked_before_persistence(base):
    for path, content in ((".env", "x"), ("a.py", 'API_KEY = "sensitive-value"')):
        with pytest.raises(DomainError):
            candidate(base, {}, [{"path": path, "operation": "create", "content": content}])
    with pytest.raises(DomainError):
        candidate(
            base,
            {b"a.py": BaselineFile(b'PASSWORD="sensitive"')},
            [{"path": "a.py", "operation": "delete"}],
        )


def test_partial_dirty_and_detached_base_cannot_propose(base):
    for changed in (
        replace(base, source_completeness="PARTIAL"),
        replace(base, dirty=True),
        replace(base, dirty=None),
        replace(base, head_state="DETACHED"),
    ):
        with pytest.raises(DomainError):
            candidate(changed, {}, [{"path": "a.py", "operation": "create", "content": "pass"}])


def test_same_text_different_request_or_base_produces_different_hash(base):
    operations = [{"path": "a.py", "operation": "create", "content": "pass"}]
    patch = candidate(base, {}, operations)
    changed = replace(base, request_intent_id=str(RequestIntentId.new()))
    assert patch.digest != candidate(changed, {}, operations).digest
    with pytest.raises(DomainError):
        require_same_base(patch, replace(base, source_snapshot_hash="d" * 64))


def test_preimage_and_unexpected_postimage_blocked(base):
    before = {b"a.py": BaselineFile(b"old")}
    patch = candidate(base, before, [{"path": "a.py", "operation": "modify", "content": "new"}])
    with pytest.raises(DomainError):
        simulate(patch, {b"a.py": BaselineFile(b"user edit")})
    after = simulate(patch, before)
    after[b"unexpected.py"] = BaselineFile(b"side effect")
    with pytest.raises(DomainError):
        require_manifest_match(patch, actual_change_set(before, after))


def test_canonical_proposal_persists_with_trusted_request_binding(environment):
    env = environment
    intent = env.patches.create_intent(
        env.repository_id, env.actor.user_id, "add a.py", "modify", "i"
    )
    base = ProposalBase(
        env.repository_id, intent, "main", "a" * 40, "b" * 64, "c" * 64, "COMPLETE", False
    )
    patch = candidate(base, {}, [{"path": "a.py", "operation": "create", "content": "pass"}])
    stored = env.patches.propose(
        user_id=env.actor.user_id,
        proposal=patch,
        key="proposal",
        classification=Classification.NORMAL,
    )
    assert stored["revision"] == 1
    row = env.db.rows(
        "SELECT proposal_base_commit,proposal_source_snapshot_hash FROM patch_revisions"
    )[0]
    assert tuple(row) == (base.commit_sha, base.source_snapshot_hash)
    assert env.patches.check_integrity()["revisions_checked"] == 1
