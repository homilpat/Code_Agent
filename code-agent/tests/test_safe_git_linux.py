import json
import shutil
import subprocess
import sys

import pytest

from kh_agent.core.canonical import encode_path
from kh_agent.repository.identity import RepositoryIdentityResolver
from kh_agent.repository.safe_git import CLEAN, SafeGitInspector

GIT = shutil.which("git") or "git"
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not shutil.which("git"),
    reason="Safe Git inspection runs on Linux with git",
)


@pytest.fixture
def git_env(tmp_path):
    home = tmp_path / "setup-home"
    home.mkdir()
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }


def runner(path, env):
    def git(*args):
        done = subprocess.run(  # noqa: S603 - test fixture setup with the resolved git binary
            [GIT, "-C", str(path), *args], env=env, check=True, capture_output=True
        )
        return done.stdout.decode().strip()

    return git


@pytest.fixture
def repo(tmp_path, git_env):
    path = tmp_path / "repo"
    path.mkdir()
    git = runner(path, git_env)
    git("init", "-q", "-b", "main")
    (path / "app.py").write_text("def app():\n    return 1\n")
    git("add", "app.py")
    git("commit", "-q", "-m", "init")
    return path, git


def inspect(path):
    return SafeGitInspector(RepositoryIdentityResolver().resolve(path), "repo_test").snapshot()


def paths(records):
    return [(record["kind"], record["path"]) for record in records]


@pytest.mark.req("M02-CTX-001")
def test_clean_repository_is_complete_mutation_ready_and_deterministic(repo):
    path, git = repo
    first, second = inspect(path), inspect(path)
    assert first.target_version == git("rev-parse", "HEAD")
    assert first.evidence["head"] == {
        "head_state": "NORMAL",
        "branch": "main",
        "commit_sha": first.target_version,
    }
    assert first.evidence["worktree"]["working_tree_diff_hash"] == CLEAN
    assert first.completeness == "COMPLETE" and first.mutation_ready
    assert first.state_digest == second.state_digest


@pytest.mark.req("M02-SNP-001", "M02-SNP-002", "M02-SNP-003")
def test_staged_unstaged_and_relevant_untracked_changes_are_recorded(repo):
    path, git = repo
    clean = inspect(path)
    (path / "lib.py").write_text("x = 1\n")
    git("add", "lib.py")
    (path / "app.py").write_text("def app():\n    return 2\n")
    (path / "new.py").write_text("y = 2\n")
    (path / "build").mkdir()
    (path / "build" / "out.py").write_text("z = 3\n")
    (path / ".env").write_text("PASSWORD=never-read-this\n")
    state = inspect(path)
    worktree = state.evidence["worktree"]
    assert paths(worktree["staged"]) == [("A", encode_path(b"lib.py"))]
    assert paths(worktree["unstaged"]) == [("MODIFIED", encode_path(b"app.py"))]
    assert paths(worktree["untracked"]) == [("UNTRACKED", encode_path(b"new.py"))]
    assert worktree["dirty"] and not state.mutation_ready
    assert worktree["working_tree_diff_hash"] != CLEAN
    assert state.state_digest != clean.state_digest
    assert "never-read-this" not in json.dumps(state.evidence)


@pytest.mark.req("M02-SNP-002")
def test_deleted_and_mode_changed_tracked_files_are_unstaged_changes(repo):
    path, git = repo
    (path / "tool.py").write_text("t = 1\n")
    git("add", "tool.py")
    git("commit", "-q", "-m", "tool")
    (path / "app.py").unlink()
    (path / "tool.py").chmod(0o755)
    unstaged = inspect(path).evidence["worktree"]["unstaged"]
    assert paths(unstaged) == [
        ("DELETED", encode_path(b"app.py")),
        ("MODE_CHANGED", encode_path(b"tool.py")),
    ]


@pytest.mark.req("M02-CTX-003")
def test_unborn_head_is_distinguished_from_a_missing_branch_ref(repo, tmp_path, git_env):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    runner(fresh, git_env)("init", "-q", "-b", "main")
    unborn = inspect(fresh)
    assert unborn.evidence["head"] == {"head_state": "UNBORN", "branch": "main", "commit_sha": None}
    assert unborn.target_version is None and not unborn.mutation_ready

    path, git = repo
    git("symbolic-ref", "HEAD", "refs/heads/gone")
    assert inspect(path).evidence["head"]["head_state"] == "UNRESOLVED"


@pytest.mark.req("M02-GIT-008", "M02-GIT-009", "M02-GIT-010", "M02-GIT-011")
def test_repository_controlled_executables_never_run_and_filtered_paths_are_not_clean(
    repo, tmp_path
):
    path, git = repo
    marker = tmp_path / "executed"
    script = tmp_path / "hostile.sh"
    script.write_text(f'#!/bin/sh\necho "$0 $*" >> {marker}\ncat\n')
    script.chmod(0o755)
    (path / ".gitattributes").write_text("*.py filter=hostile diff=hostile\n")
    git("add", ".gitattributes")
    git("commit", "-q", "-m", "attributes")
    for key in (
        "core.fsmonitor",
        "core.pager",
        "filter.hostile.clean",
        "filter.hostile.smudge",
        "filter.hostile.process",
        "diff.hostile.textconv",
        "diff.hostile.command",
        "diff.external",
        "credential.helper",
    ):
        git("config", key, str(script))
    (path / "app.py").write_text("def app():\n    return 3\n")
    state = inspect(path)
    assert not marker.exists()
    assert state.evidence["worktree"]["comparison_uncertain"] == [encode_path(b"app.py")]
    assert state.evidence["worktree"]["unstaged"] == []
    assert state.completeness == "PARTIAL" and not state.mutation_ready


@pytest.mark.req("M02-GIT-003")
def test_caller_git_environment_cannot_redirect_inspection(repo, tmp_path, git_env, monkeypatch):
    path, git = repo
    other = tmp_path / "other"
    other.mkdir()
    runner(other, git_env)("init", "-q", "-b", "main")
    for name, value in (
        ("GIT_DIR", other / ".git"),
        ("GIT_WORK_TREE", other),
        ("GIT_INDEX_FILE", other / ".git" / "index"),
        ("GIT_OBJECT_DIRECTORY", other / ".git" / "objects"),
        ("GIT_ALTERNATE_OBJECT_DIRECTORIES", other / ".git" / "objects"),
    ):
        monkeypatch.setenv(name, str(value))
    assert inspect(path).target_version == git("rev-parse", "HEAD")


@pytest.mark.req("M02-GIT-002")
def test_unauthorized_alternates_block_the_snapshot(repo, tmp_path):
    path, _ = repo
    info = path / ".git" / "objects" / "info"
    info.mkdir(exist_ok=True)
    (info / "alternates").write_text(str(tmp_path / "elsewhere" / "objects") + "\n")
    state = inspect(path)
    assert state.evidence["object_state"]["object_source_authorization"] == "UNKNOWN"
    assert state.completeness == "BLOCKED" and not state.mutation_ready


@pytest.mark.req("M02-GIT-006")
def test_replace_refs_are_detected_and_not_followed(repo):
    path, git = repo
    original = git("rev-parse", "HEAD")
    (path / "app.py").write_text("def app():\n    return 9\n")
    git("commit", "-qam", "second")
    second = git("rev-parse", "HEAD")
    git("replace", second, original)
    state = inspect(path)
    assert state.target_version == second
    assert state.evidence["object_state"]["replace_ref_count"] == 1
    assert state.evidence["worktree"]["dirty"] is False and not state.mutation_ready


@pytest.mark.req("M02-GIT-005", "M02-GIT-007")
def test_sparse_checkout_skip_worktree_and_promisor_are_recorded(repo):
    path, git = repo
    git("config", "core.sparseCheckout", "true")
    git("config", "remote.origin.promisor", "true")
    git("update-index", "--skip-worktree", "app.py")
    (path / "app.py").unlink()
    state = inspect(path)
    objects = state.evidence["object_state"]
    assert objects["sparse_checkout_enabled"] and objects["partial_clone_enabled"]
    assert objects["skip_worktree_count"] == 1
    assert state.evidence["worktree"]["unstaged"] == []
    assert state.completeness == "PARTIAL" and not state.mutation_ready


def test_in_progress_operation_blocks_mutation_readiness(repo):
    path, git = repo
    (path / ".git" / "MERGE_HEAD").write_text(git("rev-parse", "HEAD") + "\n")
    state = inspect(path)
    assert state.evidence["git_operations"] == ["MERGE_HEAD"]
    assert state.completeness == "COMPLETE" and not state.mutation_ready
