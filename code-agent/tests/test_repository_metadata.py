import os

import pytest

from kh_agent.application import Application
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.repository import identity as identity_module
from kh_agent.repository import metadata
from kh_agent.repository.identity import read_metadata
from kh_agent.repository.refs import PACKED_REFS_LIMIT, packed_ref


@pytest.mark.parametrize("width", [40, 64])
def test_packed_branch_is_declared_only(environment, width):
    git = environment.repo / ".git"
    (git / "refs/heads/main").unlink()
    (git / "packed-refs").write_bytes(
        b"# pack-refs with: peeled fully-peeled sorted\n"
        + b"b" * width
        + b" refs/heads/main\n"
        + b"c" * width
        + b" refs/tags/v1\n^"
        + b"d" * width
        + b"\n"
    )
    result = Application(environment.db).execute("status", environment.repo)
    assert result["branch"] == "main"
    assert result["declared_head_oid"] == "b" * width
    assert result["commit_sha"] is None
    assert result["working_tree_dirty"] is None
    assert result["mutation_ready"] is False


def test_loose_ref_overrides_packed(environment):
    (environment.repo / ".git/packed-refs").write_bytes(b"b" * 40 + b" refs/heads/main\n")
    result = Application(environment.db).execute("status", environment.repo)
    assert result["declared_head_oid"] == "a" * 40


def test_missing_branch_remains_unresolved(environment):
    (environment.repo / ".git/refs/heads/main").unlink()
    result = Application(environment.db).execute("status", environment.repo)
    assert result["declared_head_oid"] is None
    assert result["head_state"] == "UNRESOLVED"


@pytest.mark.parametrize(
    "ref",
    [
        b"refs/heads/../outside",
        b"refs/heads/a.lock",
        b"refs/heads/a b",
        b"refs/heads/a@{b",
        b"refs/heads/.hidden",
        b"refs/heads/a\\b",
        b"refs/heads/a:",
        b"refs/heads/a.",
        b"refs/heads/a\x00b",
    ],
)
def test_invalid_ref_blocked_before_path_lookup(environment, ref):
    (environment.repo / ".git/HEAD").write_bytes(b"ref: " + ref + b"\n")
    with pytest.raises(DomainError) as error:
        Application(environment.db).execute("status", environment.repo)
    assert error.value.code == ErrorCode.SAFE_GIT_POLICY_BLOCKED


@pytest.mark.parametrize(
    "data",
    [
        b"x" * 40 + b" refs/heads/main\n",
        (b"a" * 40 + b" refs/heads/main\n") * 2,
        b"^" + b"a" * 40 + b"\n",
        b"a" * 40 + b" refs/tags/v1\n^" + b"b" * 64 + b"\n",
        b"a" * 40 + b" refs/heads/main\n" + b"b" * 64 + b" refs/heads/other\n",
        b"a" * 40 + b" refs/heads/../outside\n",
        b"#" * (PACKED_REFS_LIMIT + 1),
    ],
    ids=["oid", "duplicate", "orphan-peel", "peel-width", "mixed-width", "path", "quota"],
)
def test_malformed_packed_refs_rejected(data):
    with pytest.raises(DomainError):
        packed_ref(data, b"refs/heads/main")


def test_ref_created_during_packed_lookup_is_blocked(environment, monkeypatch):
    git = environment.repo / ".git"
    loose = git / "refs/heads/main"
    loose.unlink()
    (git / "packed-refs").write_bytes(b"b" * 40 + b" refs/heads/main\n")
    original = metadata.read_metadata

    def changing_read(path, limit=4096):
        value = original(path, limit)
        if path.name == "packed-refs":
            loose.write_bytes(b"c" * 40 + b"\n")
        return value

    monkeypatch.setattr(metadata, "read_metadata", changing_read)
    with pytest.raises(DomainError):
        Application(environment.db).execute("status", environment.repo)


def test_metadata_change_during_read_is_blocked(tmp_path, monkeypatch):
    path = tmp_path / "HEAD"
    path.write_bytes(b"a" * 40)
    original = identity_module.os.fstat
    calls = 0

    def changing_stat(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(b"b" * 41)
        return original(fd)

    monkeypatch.setattr(identity_module.os, "fstat", changing_stat)
    with pytest.raises(DomainError):
        read_metadata(path)


def test_hardlinked_metadata_blocked(tmp_path):
    path = tmp_path / "HEAD"
    path.write_bytes(b"a" * 40)
    os.link(path, tmp_path / "alias")
    with pytest.raises(DomainError):
        read_metadata(path)
