import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kh_agent.application import Application
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.repository import identity as identity_module
from kh_agent.repository import metadata
from kh_agent.repository.identity import read_metadata
from kh_agent.repository.refs import PACKED_REFS_LIMIT, packed_ref


@pytest.mark.parametrize("width", [40, 64])
@pytest.mark.req("M02-CTX-001", partial=True)
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
    assert result["head_state"] == "NORMAL"
    assert result["commit_sha"] is None
    assert result["working_tree_dirty"] is None
    assert result["mutation_ready"] is False


def test_loose_ref_overrides_packed(environment):
    (environment.repo / ".git/packed-refs").write_bytes(b"b" * 40 + b" refs/heads/main\n")
    result = Application(environment.db).execute("status", environment.repo)
    assert result["declared_head_oid"] == "a" * 40
    assert result["head_state"] == "NORMAL"


def test_missing_branch_remains_unresolved(environment):
    (environment.repo / ".git/refs/heads/main").unlink()
    result = Application(environment.db).execute("status", environment.repo)
    assert result["declared_head_oid"] is None
    assert result["head_state"] == "UNRESOLVED"


@pytest.mark.req("M02-CTX-002", "M01-IT-006")
def test_detached_head_is_not_normal(environment):
    (environment.repo / ".git/HEAD").write_bytes(b"c" * 40 + b"\n")
    result = Application(environment.db).execute("status", environment.repo)
    assert result["branch"] is None
    assert result["head_state"] == "DETACHED"


def test_safe_git_environment_is_built_from_scratch(monkeypatch):
    from kh_agent.repository.safe_git import CONFIG_OVERRIDES, git_environment

    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_SSH_COMMAND"):
        monkeypatch.setenv(name, "hostile")
    env = git_environment("isolated-home")
    assert not {"GIT_DIR", "GIT_WORK_TREE", "GIT_ALTERNATE_OBJECT_DIRECTORIES"} & env.keys()
    assert "GIT_SSH_COMMAND" not in env and env["HOME"] == "isolated-home"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
    for override in ("core.fsmonitor=false", "credential.helper=", "protocol.allow=never"):
        assert override in CONFIG_OVERRIDES


@pytest.mark.req("M02-CTX-004", "M02-CTX-005", "M02-CTX-006")
@pytest.mark.parametrize(
    "marker, is_directory",
    [
        ("MERGE_HEAD", False),
        ("rebase-merge", True),
        ("rebase-apply", True),
        ("CHERRY_PICK_HEAD", False),
        ("REVERT_HEAD", False),
        ("sequencer", True),
    ],
)
def test_in_progress_git_operation_is_reported_and_not_mutation_ready(
    environment, marker, is_directory
):
    path = environment.repo / ".git" / marker
    if is_directory:
        path.mkdir()
    else:
        path.write_bytes(b"a" * 40 + b"\n")
    result = Application(environment.db).execute("status", environment.repo)
    assert result["git_operation_state"] == "IN_PROGRESS"
    assert result["git_operations"] == [marker]
    assert result["mutation_ready"] is False


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
@pytest.mark.req("M02-CTX-007")
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
@pytest.mark.req("M02-CTX-007")
def test_malformed_packed_refs_rejected(data):
    with pytest.raises(DomainError):
        packed_ref(data, b"refs/heads/main")


@pytest.mark.req("M02-CTX-007")
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


@pytest.mark.req("M02-CTX-007")
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


@pytest.mark.parametrize("field", ["st_ctime_ns", "st_mtime_ns"])
def test_path_stat_ctime_lag_tolerated_only_off_linux(tmp_path, monkeypatch, field):
    path = tmp_path / "HEAD"
    path.write_bytes(b"a" * 40)
    real_lstat = Path.lstat
    names = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")

    def lagging_lstat(self, *args, **kwargs):
        value = real_lstat(self, *args, **kwargs)
        fields = {name: getattr(value, name) for name in names}
        fields["st_file_attributes"] = getattr(value, "st_file_attributes", 0)
        fields[field] -= 1_000_000
        return SimpleNamespace(**fields)

    monkeypatch.setattr(Path, "lstat", lagging_lstat)
    if field == "st_ctime_ns" and sys.platform != "linux":
        assert read_metadata(path) == b"a" * 40
    else:
        with pytest.raises(DomainError):
            read_metadata(path)


@pytest.mark.req("M02-CTX-007")
def test_hardlinked_metadata_blocked(tmp_path):
    path = tmp_path / "HEAD"
    path.write_bytes(b"a" * 40)
    os.link(path, tmp_path / "alias")
    with pytest.raises(DomainError):
        read_metadata(path)
