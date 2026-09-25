import json
import os
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from kh_agent.application import Application
from kh_agent.cli.app import app as cli_app
from kh_agent.core.canonical import encode_path
from kh_agent.core.enums import Permission
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.identity.service import Identity
from kh_agent.patch.file_writer import replace_source_file
from kh_agent.repository.identity import RepositoryIdentityResolver
from kh_agent.repository.safe_git import CLEAN, SafeGitInspector, inspect_target, revalidate_target
from kh_agent.repository.snapshot import SourceScanner
from kh_agent.sandbox.container import SandboxResult
from kh_agent.sandbox.lsp import Diagnostic, Location
from kh_agent.security.ingestion import IngestionPolicy
from kh_agent.store.database import Database
from kh_agent.store.registry import Registry
from kh_agent.store.worktree_journal import WorktreeWriteJournal, journaled_replace_source_file

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


def test_gitignored_source_is_not_certified_as_clean(repo):
    path, git = repo
    (path / ".gitignore").write_text("*.pyc\nignored/\nbuild/\n")
    git("add", ".gitignore")
    git("commit", "-q", "-m", "ignore rules")
    baseline = inspect(path)
    assert baseline.mutation_ready
    (path / "ignored").mkdir()
    (path / "ignored" / "config.py").write_text("VALUE = 1\n")
    (path / "build").mkdir()
    (path / "build" / "generated.py").write_text("VALUE = 2\n")
    (path / "cache.pyc").write_bytes(b"cache")
    (path / "runtime.log").write_text("ordinary log output\n")
    current = inspect(path)
    assert paths(current.evidence["worktree"]["untracked"]) == [
        ("UNTRACKED", encode_path(b"ignored/config.py")),
    ]
    assert current.evidence["worktree"]["dirty"]
    assert not current.mutation_ready and current.state_digest != baseline.state_digest


def test_policy_content_changes_target_digest_even_at_the_same_version(repo):
    path, _ = repo
    identity = RepositoryIdentityResolver().resolve(path)
    default = inspect_target(identity, "repo_test")
    policy = IngestionPolicy(
        excluded_directories=IngestionPolicy().excluded_directories | {"cache"}
    )
    changed = inspect_target(identity, "repo_test", policy)
    assert (
        default.evidence["ingestion_policy_version"] == changed.evidence["ingestion_policy_version"]
    )
    assert default.state_digest != changed.state_digest


def test_revalidate_target_rejects_changes_since_the_baseline(repo):
    path, _ = repo
    identity = RepositoryIdentityResolver().resolve(path)
    baseline = inspect_target(identity, "repo_test")
    assert revalidate_target(baseline, identity, "repo_test").state_digest == baseline.state_digest
    (path / "app.py").write_text("def app():\n    return 2\n")
    with pytest.raises(DomainError) as changed:
        revalidate_target(baseline, identity, "repo_test")
    assert changed.value.code == ErrorCode.DIRTY_WORKTREE_BLOCKED
    (path / "app.py").write_text("def app():\n    return 1\n")
    (path / "new.py").write_text("VALUE = 1\n")
    with pytest.raises(DomainError) as untracked:
        revalidate_target(baseline, identity, "repo_test")
    assert untracked.value.code == ErrorCode.DIRTY_WORKTREE_BLOCKED
    (path / "new.py").unlink()
    with pytest.raises(DomainError) as wrong_repository:
        revalidate_target(baseline, identity, "another_repo")
    assert wrong_repository.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED


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


@pytest.fixture
def application(tmp_path, monkeypatch):
    opened = []

    def build(path):
        db = Database(tmp_path / "store" / f"kh-{len(opened)}.db")
        opened.append(db)
        registry = Registry(db)
        actor = Identity(registry.bootstrap("linux-uid:1000"), "OS_MAPPING")
        monkeypatch.setattr(
            "kh_agent.identity.service.current_os_principal", lambda: "linux-uid:1000"
        )
        registry.register(actor, RepositoryIdentityResolver().resolve(path), "register")
        return Application(db, target_inspector=inspect_target)

    yield build
    for db in opened:
        db.close()


def test_status_reports_the_safe_git_target(repo, application):
    path, git = repo
    app = application(path)
    clean = app.execute("status", path)
    assert clean["inspection_scope"] == "SAFE_GIT_PLUMBING"
    assert clean["commit_sha"] == git("rev-parse", "HEAD")
    assert clean["working_tree_dirty"] is False and clean["mutation_ready"] is True
    (path / "app.py").write_text("def app():\n    return 5\n")
    dirty = app.execute("status", path)
    assert dirty["working_tree_dirty"] is True and dirty["unstaged_changes"] == 1
    assert dirty["mutation_ready"] is False
    assert dirty["target_state_digest"] != clean["target_state_digest"]


def test_semantic_query_limits_paths_and_detects_source_change(repo, application, monkeypatch):
    path, _ = repo
    app = application(path)
    seen = []

    class FakeSession:
        def __init__(self, stdin, stdout, on_failure):
            pass

        def close(self):
            seen.append("closed")

    class FakeClient:
        def __init__(self, session, request_timeout):
            assert request_timeout == 90

        def open(self, target, content):
            assert (target, content) == ("app.py", "def app():\n    return 1\n")

        def definition(self, target, line, column):
            assert (target, line, column) == ("app.py", 0, 4)
            return (Location("app.py", 0, 4, 0, 7), Location(None, 1, 0, 1, 2))

        def references(self, target, line, column):
            if seen and seen[0] == "change":
                (path / "app.py").write_text("def changed(): pass\n")
            return (Location("excluded.py", 0, 0, 0, 1), Location("app.py", 0, 4, 0, 7))

        def diagnostics(self, target):
            return (Diagnostic(target, 1, 3, 1, "reportProblem", "bad value"),)

    class FakeBackend:
        def __init__(self, image):
            assert image == "a" * 64

        @contextmanager
        def language_server(self, command, snapshot):
            assert command.template_id == "python-language-server"
            assert snapshot.completeness == "PARTIAL"
            yield SimpleNamespace(stdin=None, stdout=None, kill=lambda: None,
                                  plan_hash="b" * 64, attestation_digest="c" * 64)

    monkeypatch.setattr("kh_agent.application.LspSession", FakeSession)
    monkeypatch.setattr("kh_agent.application.PythonLanguageClient", FakeClient)
    app.sandbox_factory = FakeBackend
    result = app.semantic_query(path, "app.py", 1, 5, "a" * 64)
    assert result["definitions"] == [{"path": "app.py", "line": 1, "column": 5}]
    assert result["definitions_outside_view"] == 1
    assert result["references_outside_view"] == 1
    assert result["diagnostics"][0]["line"] == 2
    assert result["source_completeness"] == "PARTIAL"
    assert "THIRD_PARTY_DEPENDENCIES_NOT_MOUNTED" in result["limitations"]
    assert seen == ["closed"]

    with pytest.raises(DomainError) as invalid:
        app.semantic_query(path, "app.py", 0, 5, "a" * 64)
    assert invalid.value.code == ErrorCode.INVALID_INPUT
    seen[:] = ["change"]
    with pytest.raises(DomainError) as changed:
        app.semantic_query(path, "app.py", 1, 5, "a" * 64)
    assert changed.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED


def test_mutation_gate_rejects_change_between_two_inspections(repo, application):
    path, _ = repo
    app = application(path)
    calls = 0

    def changing_inspector(identity, repository_id):
        nonlocal calls
        state = inspect_target(identity, repository_id)
        calls += 1
        if calls == 1:
            (path / "app.py").write_text("def app():\n    return 99\n")
        return state

    app.target_inspector = changing_inspector
    with pytest.raises(DomainError) as error:
        app.execute("modify", path)
    assert calls == 2
    assert error.value.code == ErrorCode.DIRTY_WORKTREE_BLOCKED


def test_mutation_gate_rejects_a_different_clean_commit(repo, application):
    path, git = repo
    app = application(path)
    calls = 0

    def advancing_inspector(identity, repository_id):
        nonlocal calls
        state = inspect_target(identity, repository_id)
        calls += 1
        if calls == 1:
            (path / "app.py").write_text("def app():\n    return 3\n")
            git("commit", "-qam", "advance")
        return state

    app.target_inspector = advancing_inspector
    with pytest.raises(DomainError) as error:
        app.execute("modify", path)
    assert calls == 2
    assert error.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED


def test_candidate_preview_shows_a_diff_without_writing_to_repository(repo, application, tmp_path):
    path, git = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "path": "app.py",
                        "operation": "modify",
                        "content": "def app():\n    return 2\n",
                    }
                ]
            }
        )
    )
    original = (path / "app.py").read_bytes()
    before = git("rev-parse", "HEAD")
    result = app.preview(path, candidate)
    assert result["status"] == "PREVIEW_ONLY"
    assert result["source_completeness"] == "PARTIAL"
    assert "-    return 1" in result["diff"] and "+    return 2" in result["diff"]
    assert (path / "app.py").read_bytes() == original
    assert git("rev-parse", "HEAD") == before


def test_candidate_preview_rejects_a_path_outside_safe_source(repo, application, tmp_path):
    path, _ = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "operations": [
                    {"path": "../other.py", "operation": "modify", "content": "VALUE = 1\n"}
                ]
            }
        )
    )
    with pytest.raises(DomainError) as error:
        app.preview(path, candidate)
    assert error.value.code == ErrorCode.INVALID_INPUT


def test_candidate_preview_needs_code_read_permission(repo, application, tmp_path):
    path, _ = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "path": "app.py",
                        "operation": "modify",
                        "content": "def app():\n    return 2\n",
                    }
                ]
            }
        )
    )
    actor = app.identities.resolve()
    repository_id = app.registry.lookup(RepositoryIdentityResolver().resolve(path))
    app.registry.permission(
        actor, actor.user_id, repository_id, Permission.CODE_ANALYZE, grant=False
    )
    with pytest.raises(DomainError) as error:
        app.preview(path, candidate)
    assert error.value.code == ErrorCode.ACCESS_DENIED


def test_preview_candidate_cli_routes_to_read_only_preview(
    repo, application, tmp_path, monkeypatch
):
    path, _ = repo
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {"operations": [{"path": "app.py", "operation": "modify", "content": "VALUE = 2\n"}]}
        )
    )
    instance = application(path)
    monkeypatch.setattr("kh_agent.cli.app.require_linux_store", lambda root: root)
    monkeypatch.setattr(
        "kh_agent.cli.app.Database", lambda path: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr("kh_agent.cli.app._application", lambda ctx, db: instance)
    result = CliRunner().invoke(cli_app, ["preview-candidate", str(candidate), "--repo", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "PREVIEW_ONLY"
    assert (path / "app.py").read_text() == "def app():\n    return 1\n"


def test_candidate_verification_passes_only_the_modified_view_to_sandbox(
    repo, application, tmp_path
):
    path, _ = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "path": "app.py",
                        "operation": "modify",
                        "content": "def app():\n    return 7\n",
                    }
                ]
            }
        )
    )

    class CapturingBackend:
        def __init__(self, image):
            assert image == "a" * 64

        def execute(self, command, snapshot):
            assert command.argv[-1] == "tests/test_app.py"
            assert {source.path: source.content for source in snapshot.files}[b"app.py"] == (
                b"def app():\n    return 7\n"
            )
            assert snapshot.completeness == "PARTIAL"
            return SandboxResult("PASS", 0, "EXITED", "1 passed", False, "d" * 64, 1.0, "p", "a")

    app.sandbox_factory = CapturingBackend
    result = app.verify_candidate(path, candidate, "a" * 64, ("tests/test_app.py",))
    assert result["status"] == "EXPERIMENTAL_TEST_ONLY"
    assert result["test_status"] == "PASS" and result["apply_ready"] is False
    assert (path / "app.py").read_text() == "def app():\n    return 1\n"


def test_candidate_verification_rejects_repository_change_during_test(repo, application, tmp_path):
    path, _ = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {"operations": [{"path": "app.py", "operation": "modify", "content": "VALUE = 1\n"}]}
        )
    )

    class ChangingBackend:
        def __init__(self, image):
            pass

        def execute(self, command, snapshot):
            (path / "app.py").write_text("changed during test\n")
            return SandboxResult("PASS", 0, "EXITED", "1 passed", False, "d" * 64, 1.0, "p", "a")

    app.sandbox_factory = ChangingBackend
    with pytest.raises(DomainError) as error:
        app.verify_candidate(path, candidate, "a" * 64, ("tests/test_app.py",))
    assert error.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED


def test_local_model_generation_only_previews_the_authorized_target(repo, application):
    path, _ = repo
    app = application(path)

    class FakeModel:
        def __init__(self, model, port):
            assert (model, port) == ("local/model", 1234)

        def generate(self, request, target, source):
            assert (request, target, source) == (
                "Change the return value",
                "app.py",
                b"def app():\n    return 1\n",
            )
            return json.dumps(
                {
                    "operations": [
                        {
                            "path": "app.py",
                            "operation": "modify",
                            "content": "def app():\n    return 8\n",
                        }
                    ]
                }
            ).encode()

    app.model_factory = FakeModel
    result = app.generate_preview(path, "app.py", "Change the return value", "local/model")
    assert result["status"] == "MODEL_PREVIEW_ONLY" and result["apply_ready"] is False
    assert "+    return 8" in result["diff"]
    assert result["candidate"]["operations"][0]["content"] == "def app():\n    return 8\n"
    assert (path / "app.py").read_text() == "def app():\n    return 1\n"


def test_model_generated_candidate_runs_once_in_ephemeral_test_view(repo, application):
    path, git = repo
    app = application(path)
    calls = []

    class FakeModel:
        def __init__(self, model, port):
            assert (model, port) == ("local/model", 1234)

        def generate(self, request, target, source):
            calls.append((request, target, source))
            return json.dumps(
                {"operations": [{"path": "app.py", "operation": "modify",
                                 "content": "def app():\n    return 8\n"}]}
            ).encode()

    class FakeBackend:
        def __init__(self, image):
            assert image == "a" * 64

        def execute(self, command, snapshot):
            assert command.argv[-1] == "tests/test_app.py"
            assert next(item for item in snapshot.files if item.path == b"app.py").content == (
                b"def app():\n    return 8\n"
            )
            return SandboxResult("PASS", 0, "EXITED", "1 passed", False, "d" * 64, 1.0, "p", "a")

    app.model_factory = FakeModel
    app.sandbox_factory = FakeBackend
    head = git("rev-parse", "HEAD")
    result = app.generate_and_verify(
        path, "app.py", "Change the return value", "local/model", "a" * 64,
        ("tests/test_app.py",),
    )
    assert calls == [("Change the return value", "app.py", b"def app():\n    return 1\n")]
    assert result["status"] == "MODEL_TEST_EXPERIMENTAL"
    assert result["apply_ready"] is False and result["test_status"] == "PASS"
    assert result["source_completeness"] == "PARTIAL"
    assert result["candidate"]["operations"][0]["content"] == "def app():\n    return 8\n"
    assert (path / "app.py").read_text() == "def app():\n    return 1\n"
    assert git("rev-parse", "HEAD") == head


def test_generated_test_result_rejected_when_backend_changes_repository(repo, application):
    path, _ = repo
    app = application(path)

    class FakeModel:
        def __init__(self, model, port):
            pass

        def generate(self, request, target, source):
            return json.dumps(
                {"operations": [{"path": "app.py", "operation": "modify", "content": "x = 1\n"}]}
            ).encode()

    class ChangingBackend:
        def __init__(self, image):
            pass

        def execute(self, command, snapshot):
            (path / "app.py").write_text("changed during test\n")
            return SandboxResult("PASS", 0, "EXITED", "1 passed", False, "d" * 64, 1.0, "p", "a")

    app.model_factory = FakeModel
    app.sandbox_factory = ChangingBackend
    with pytest.raises(DomainError) as error:
        app.generate_and_verify(
            path, "app.py", "change", "local/model", "a" * 64, ("tests/test_app.py",)
        )
    assert error.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED


def test_worktree_writer_replaces_only_the_bound_regular_file(repo):
    path, git = repo
    identity = RepositoryIdentityResolver().resolve(path)
    scanner = SourceScanner()
    original = next(item for item in scanner.scan(identity).files if item.path == b"app.py")
    checked = []
    before = inspect(path)

    def precommit():
        checked.append(True)
        assert inspect(path).state_digest == before.state_digest
        assert scanner.scan(identity).snapshot_hash == baseline_hash

    baseline_hash = scanner.scan(identity).snapshot_hash
    digest = replace_source_file(
        identity, original, b"def app():\n    return 8\n", precommit=precommit
    )
    assert checked == [True]
    assert len(digest) == 64
    assert (path / "app.py").read_text() == "def app():\n    return 8\n"
    assert stat.S_IMODE((path / "app.py").stat().st_mode) == 0o644
    assert git("rev-parse", "HEAD") == before.target_version
    assert not list(path.glob(".kh-replacement-*"))
    assert not inspect(path).mutation_ready


def test_worktree_writer_refuses_file_change_during_precommit(repo):
    path, _ = repo
    identity = RepositoryIdentityResolver().resolve(path)
    source = next(item for item in SourceScanner().scan(identity).files if item.path == b"app.py")

    def change():
        (path / "app.py").write_text("changed during check\n")

    with pytest.raises(DomainError) as error:
        replace_source_file(identity, source, b"x = 8\n", precommit=change)
    assert error.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED
    assert (path / "app.py").read_text() == "changed during check\n"
    assert not list(path.glob(".kh-replacement-*"))


def test_worktree_writer_refuses_symlink_or_hardlink(repo, tmp_path):
    path, _ = repo
    identity = RepositoryIdentityResolver().resolve(path)
    source = next(item for item in SourceScanner().scan(identity).files if item.path == b"app.py")
    original = (path / "app.py").read_bytes()
    (path / "app.py").unlink()
    (path / "app.py").symlink_to(tmp_path / "elsewhere.py")
    with pytest.raises(DomainError):
        replace_source_file(identity, source, b"x = 8\n", precommit=lambda: None)
    (path / "app.py").unlink()
    (path / "app.py").write_bytes(original)
    os.link(path / "app.py", tmp_path / "other-link.py")
    with pytest.raises(DomainError):
        replace_source_file(identity, source, b"x = 8\n", precommit=lambda: None)
    assert (path / "app.py").read_bytes() == original


def test_worktree_journal_records_write_before_replacement(repo, application):
    path, _ = repo
    app = application(path)
    identity = RepositoryIdentityResolver().resolve(path)
    repository_id = app.registry.lookup(identity)
    actor = app.identities.resolve()
    source_snapshot = SourceScanner().scan(identity)
    source = next(item for item in source_snapshot.files if item.path == b"app.py")
    target = inspect_target(identity, repository_id)
    journal = WorktreeWriteJournal(app.db)

    def precommit():
        assert journal.pending(repository_id)
        assert inspect_target(identity, repository_id).state_digest == target.state_digest

    result = journaled_replace_source_file(
        journal, repository_id, actor.user_id, identity, source,
        b"def app():\n    return 9\n",
        source_snapshot_hash=source_snapshot.snapshot_hash,
        target_state_digest=target.state_digest,
        precommit=precommit,
    )
    assert len(result) == 64
    assert not journal.pending(repository_id)
    rows = app.db.rows(
        "SELECT event_type FROM audit_events WHERE event_type LIKE 'WORKTREE_WRITE_%' "
        "ORDER BY sequence"
    )
    assert [row["event_type"] for row in rows] == [
        "WORKTREE_WRITE_PREPARED", "WORKTREE_WRITE_FINISHED"
    ]


def test_failed_completion_leaves_durable_pending_write(repo, application):
    path, _ = repo
    app = application(path)
    identity = RepositoryIdentityResolver().resolve(path)
    repository_id = app.registry.lookup(identity)
    actor = app.identities.resolve()
    snapshot = SourceScanner().scan(identity)
    source = next(item for item in snapshot.files if item.path == b"app.py")
    journal = WorktreeWriteJournal(app.db)
    with app.db.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER fail_completion BEFORE INSERT ON audit_events "
            "WHEN NEW.event_type='WORKTREE_WRITE_FINISHED' BEGIN "
            "SELECT RAISE(ABORT, 'failure'); END"
        )
    parameters = {
        "source_snapshot_hash": snapshot.snapshot_hash,
        "target_state_digest": inspect_target(identity, repository_id).state_digest,
        "precommit": lambda: None,
    }
    with pytest.raises(DomainError) as error:
        journaled_replace_source_file(
            journal, repository_id, actor.user_id, identity, source, b"x = 9\n", **parameters
        )
    assert error.value.code == ErrorCode.CRITICAL_PERSISTENCE_FAILED
    assert (path / "app.py").read_text() == "x = 9\n"
    pending = journal.pending(repository_id)
    assert len(pending) == 1
    db_path = app.db.rows("PRAGMA database_list")[0][2]
    reopened = Database(Path(db_path))
    try:
        assert WorktreeWriteJournal(reopened).pending(repository_id) == pending
        with pytest.raises(DomainError) as blocked:
            WorktreeWriteJournal(reopened).prepare(
                repository_id, actor.user_id, path=b"app.py",
                before_sha256=source.content_hash, after_sha256="e" * 64,
                **{key: parameters[key] for key in ("source_snapshot_hash", "target_state_digest")},
            )
        assert blocked.value.code == ErrorCode.CRITICAL_PERSISTENCE_FAILED
        assert WorktreeWriteJournal(reopened).reconcile(
            repository_id, actor.user_id, pending[0], identity, b"app.py"
        ) == "REPLACEMENT_BYTES"
        assert WorktreeWriteJournal(reopened).pending(repository_id) == []
    finally:
        reopened.close()


def test_pending_write_blocks_status_readiness_even_when_git_is_clean(repo, application):
    path, _ = repo
    app = application(path)
    identity = RepositoryIdentityResolver().resolve(path)
    repository_id = app.registry.lookup(identity)
    actor = app.identities.resolve()
    snapshot = SourceScanner().scan(identity)
    source = next(item for item in snapshot.files if item.path == b"app.py")
    journal = WorktreeWriteJournal(app.db)

    def interrupt():
        raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Interrupted before rename")

    with pytest.raises(DomainError):
        journaled_replace_source_file(
            journal, repository_id, actor.user_id, identity, source, b"x = 9\n",
            source_snapshot_hash=snapshot.snapshot_hash,
            target_state_digest=inspect_target(identity, repository_id).state_digest,
            precommit=interrupt,
        )
    status = app.execute("status", path)
    assert status["working_tree_dirty"] is False
    assert status["unresolved_worktree_writes"] == 1
    assert status["mutation_ready"] is False
    assert (path / "app.py").read_text() == "def app():\n    return 1\n"
    assert status["unresolved_write_attempts"] == journal.pending(repository_id)
    recovered = app.reconcile_write(path, status["unresolved_write_attempts"][0], "app.py")
    assert recovered["observed"] == "ORIGINAL_BYTES"
    assert app.execute("status", path)["mutation_ready"] is True


def test_reconciliation_refuses_unknown_bytes_and_keeps_pending(repo, application):
    path, _ = repo
    app = application(path)
    identity = RepositoryIdentityResolver().resolve(path)
    repository_id = app.registry.lookup(identity)
    actor = app.identities.resolve()
    snapshot = SourceScanner().scan(identity)
    source = next(item for item in snapshot.files if item.path == b"app.py")
    journal = WorktreeWriteJournal(app.db)

    def interrupt():
        raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED)

    with pytest.raises(DomainError):
        journaled_replace_source_file(
            journal, repository_id, actor.user_id, identity, source, b"x = 9\n",
            source_snapshot_hash=snapshot.snapshot_hash,
            target_state_digest=inspect_target(identity, repository_id).state_digest,
            precommit=interrupt,
        )
    (path / "app.py").write_text("x = 999\n")
    pending = journal.pending(repository_id)
    with pytest.raises(DomainError) as unknown:
        journal.reconcile(repository_id, actor.user_id, pending[0], identity, b"app.py")
    assert unknown.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED
    assert journal.pending(repository_id) == pending


def test_explicit_candidate_apply_requires_reviewed_hash_and_fresh_passing_test(
    repo, application, tmp_path
):
    path, git = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "operations": [{"path": "app.py", "operation": "modify",
                        "content": "def app():\n    return 42\n"}]
    }))
    review = app.preview(path, candidate)
    reviewed = review["candidate_hash"]
    seen = []

    class PassingBackend:
        def __init__(self, image):
            assert image == "a" * 64

        def execute(self, command, snapshot):
            seen.append((command.argv[-1], snapshot.files[0].content))
            return SandboxResult(
                "PASS", 0, "EXITED", "1 passed", False, "d" * 64,
                1.0, "b" * 64, "c" * 64,
            )

    app.sandbox_factory = PassingBackend
    with pytest.raises(DomainError) as wrong:
        app.apply_tested_candidate(path, candidate, "e" * 64,
                                   review["source_snapshot_hash"], review["target_state_digest"],
                                   "a" * 64,
                                   ("tests/test_app.py",))
    assert wrong.value.code == ErrorCode.VERIFICATION_BASIS_MISMATCH
    assert seen == [] and (path / "app.py").read_text() == "def app():\n    return 1\n"
    with pytest.raises(DomainError) as wrong_base:
        app.apply_tested_candidate(
            path, candidate, reviewed, "e" * 64, review["target_state_digest"],
            "a" * 64, ("tests/test_app.py",)
        )
    assert wrong_base.value.code == ErrorCode.VERIFICATION_BASIS_MISMATCH
    assert seen == []
    before = git("rev-parse", "HEAD")
    result = app.apply_tested_candidate(
        path, candidate, reviewed, review["source_snapshot_hash"],
        review["target_state_digest"], "a" * 64, ("tests/test_app.py",)
    )
    assert seen == [("tests/test_app.py", b"def app():\n    return 42\n")]
    assert result["status"] == "EXPERIMENTAL_APPLIED"
    assert result["formal_verification"] is False
    assert result["candidate_hash"] == reviewed
    assert (path / "app.py").read_text() == "def app():\n    return 42\n"
    assert git("rev-parse", "HEAD") == before
    assert app.execute("status", path)["working_tree_dirty"] is True
    assert app.execute("status", path)["unresolved_worktree_writes"] == 0
    event = app.db.rows(
        "SELECT payload_json FROM audit_events WHERE event_type='WORKTREE_WRITE_PREPARED'"
    )[0]
    evidence = json.loads(event["payload_json"])
    assert evidence["candidate_hash"] == reviewed
    assert evidence["source_snapshot_hash"] == review["source_snapshot_hash"]
    assert evidence["test_plan_hash"] == "b" * 64
    assert evidence["test_attestation_digest"] == "c" * 64


def test_candidate_apply_refuses_failed_test_without_writing(repo, application, tmp_path):
    path, _ = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "operations": [{"path": "app.py", "operation": "modify", "content": "x = 42\n"}]
    }))
    review = app.preview(path, candidate)
    reviewed = review["candidate_hash"]

    class FailingBackend:
        def __init__(self, image):
            pass

        def execute(self, command, snapshot):
            return SandboxResult(
                "FAIL", 1, "EXITED", "1 failed", False, "d" * 64,
                1.0, "b" * 64, "c" * 64,
            )

    app.sandbox_factory = FailingBackend
    with pytest.raises(DomainError) as failed:
        app.apply_tested_candidate(path, candidate, reviewed,
                                   review["source_snapshot_hash"], review["target_state_digest"],
                                   "a" * 64,
                                   ("tests/test_app.py",))
    assert failed.value.code == ErrorCode.PATCH_NOT_VERIFIED
    assert (path / "app.py").read_text() == "def app():\n    return 1\n"
    assert not WorktreeWriteJournal(app.db).pending(app.registry.lookup(
        RepositoryIdentityResolver().resolve(path)))


def test_candidate_apply_rejects_repository_change_during_test(repo, application, tmp_path):
    path, _ = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "operations": [{"path": "app.py", "operation": "modify", "content": "x = 42\n"}]
    }))
    review = app.preview(path, candidate)
    reviewed = review["candidate_hash"]

    class ChangingBackend:
        def __init__(self, image):
            pass

        def execute(self, command, snapshot):
            (path / "app.py").write_text("changed during test\n")
            return SandboxResult(
                "PASS", 0, "EXITED", "1 passed", False, "d" * 64,
                1.0, "b" * 64, "c" * 64,
            )

    app.sandbox_factory = ChangingBackend
    with pytest.raises(DomainError) as changed:
        app.apply_tested_candidate(path, candidate, reviewed,
                                   review["source_snapshot_hash"], review["target_state_digest"],
                                   "a" * 64,
                                   ("tests/test_app.py",))
    assert changed.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED
    assert (path / "app.py").read_text() == "changed during test\n"
    assert not WorktreeWriteJournal(app.db).pending(app.registry.lookup(
        RepositoryIdentityResolver().resolve(path)))


def test_candidate_apply_needs_current_apply_permission(repo, application, tmp_path):
    path, _ = repo
    app = application(path)
    actor = app.identities.resolve()
    repository_id = app.registry.lookup(RepositoryIdentityResolver().resolve(path))
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "operations": [{"path": "app.py", "operation": "modify", "content": "x = 42\n"}]
    }))
    review = app.preview(path, candidate)
    reviewed = review["candidate_hash"]
    app.registry.permission(
        actor, actor.user_id, repository_id, Permission.PATCH_APPLY, grant=False
    )
    with pytest.raises(DomainError) as denied:
        app.apply_tested_candidate(path, candidate, reviewed,
                                   review["source_snapshot_hash"], review["target_state_digest"],
                                   "a" * 64,
                                   ("tests/test_app.py",))
    assert denied.value.code == ErrorCode.ACCESS_DENIED
    assert (path / "app.py").read_text() == "def app():\n    return 1\n"


def test_candidate_apply_refuses_reviewed_base_after_new_commit(repo, application, tmp_path):
    path, git = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "operations": [{"path": "app.py", "operation": "modify", "content": "x = 42\n"}]
    }))
    review = app.preview(path, candidate)
    (path / "app.py").write_text("def app():\n    return 3\n")
    git("commit", "-qam", "advance")
    with pytest.raises(DomainError) as stale:
        app.apply_tested_candidate(
            path, candidate, review["candidate_hash"], review["source_snapshot_hash"],
            review["target_state_digest"], "a" * 64, ("tests/test_app.py",)
        )
    assert stale.value.code == ErrorCode.VERIFICATION_BASIS_MISMATCH
    assert (path / "app.py").read_text() == "def app():\n    return 3\n"


def test_candidate_apply_rechecks_permission_after_test(repo, application, tmp_path):
    path, _ = repo
    app = application(path)
    actor = app.identities.resolve()
    repository_id = app.registry.lookup(RepositoryIdentityResolver().resolve(path))
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "operations": [{"path": "app.py", "operation": "modify", "content": "x = 42\n"}]
    }))
    review = app.preview(path, candidate)

    class RevokingBackend:
        def __init__(self, image):
            pass

        def execute(self, command, snapshot):
            app.registry.permission(
                actor, actor.user_id, repository_id, Permission.PATCH_APPLY, grant=False
            )
            return SandboxResult(
                "PASS", 0, "EXITED", "1 passed", False, "d" * 64,
                1.0, "b" * 64, "c" * 64,
            )

    app.sandbox_factory = RevokingBackend
    with pytest.raises(DomainError) as denied:
        app.apply_tested_candidate(
            path, candidate, review["candidate_hash"], review["source_snapshot_hash"],
            review["target_state_digest"], "a" * 64, ("tests/test_app.py",)
        )
    assert denied.value.code == ErrorCode.ACCESS_DENIED
    assert (path / "app.py").read_text() == "def app():\n    return 1\n"


def test_candidate_apply_leaves_pending_if_repository_changes_after_rename(
    repo, application, tmp_path, monkeypatch
):
    path, _ = repo
    app = application(path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "operations": [{"path": "app.py", "operation": "modify", "content": "x = 42\n"}]
    }))
    review = app.preview(path, candidate)

    class PassingBackend:
        def __init__(self, image):
            pass

        def execute(self, command, snapshot):
            return SandboxResult(
                "PASS", 0, "EXITED", "1 passed", False, "d" * 64,
                1.0, "b" * 64, "c" * 64,
            )

    app.sandbox_factory = PassingBackend
    real_replace = os.replace

    def race_replace(source, target, *, src_dir_fd, dst_dir_fd):
        real_replace(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        (path / "other.py").write_text("unexpected = True\n")

    monkeypatch.setattr("kh_agent.patch.file_writer.os.replace", race_replace)
    with pytest.raises(DomainError) as changed:
        app.apply_tested_candidate(
            path, candidate, review["candidate_hash"], review["source_snapshot_hash"],
            review["target_state_digest"], "a" * 64, ("tests/test_app.py",)
        )
    assert changed.value.code == ErrorCode.REPOSITORY_STATE_BLOCKED
    assert (path / "app.py").read_text() == "x = 42\n"
    status = app.execute("status", path)
    assert status["unresolved_worktree_writes"] == 1 and status["mutation_ready"] is False


def test_local_model_cannot_redirect_candidate_to_another_file(repo, application):
    path, git = repo
    (path / "other.py").write_text("x = 0\n")
    git("add", "other.py")
    git("commit", "-q", "-m", "other source")
    app = application(path)

    class WrongTargetModel:
        def __init__(self, model, port):
            pass

        def generate(self, request, target, source):
            return json.dumps(
                {"operations": [{"path": "other.py", "operation": "modify", "content": "x = 1\n"}]}
            ).encode()

    app.model_factory = WrongTargetModel
    with pytest.raises(DomainError) as error:
        app.generate_preview(path, "app.py", "Change return", "local/model")
    assert error.value.code == ErrorCode.INVALID_INPUT


@pytest.mark.req("M01-IT-007")
@pytest.mark.req("M01-IT-008", "M01-IT-009", partial=True)  # APPLY is not implemented yet
@pytest.mark.parametrize(
    "state, code",
    [
        ("detached", ErrorCode.REPOSITORY_STATE_BLOCKED),
        ("merge", ErrorCode.REPOSITORY_STATE_BLOCKED),
        ("rebase", ErrorCode.REPOSITORY_STATE_BLOCKED),
        ("dirty", ErrorCode.DIRTY_WORKTREE_BLOCKED),
        ("filtered", ErrorCode.REPOSITORY_STATE_BLOCKED),
    ],
)
def test_mutation_commands_are_blocked_on_an_unsafe_target(repo, application, state, code):
    path, git = repo
    app = application(path)
    with pytest.raises(DomainError) as ready:
        app.execute("modify", path)
    assert ready.value.code == ErrorCode.CAPABILITY_NOT_AVAILABLE
    if state == "detached":
        git("checkout", "-q", "--detach")
    elif state == "merge":
        (path / ".git" / "MERGE_HEAD").write_text(git("rev-parse", "HEAD") + "\n")
    elif state == "rebase":
        (path / ".git" / "rebase-merge").mkdir()
    elif state == "dirty":
        (path / "app.py").write_text("changed = True\n")
    else:
        (path / ".gitattributes").write_text("*.py filter=lfs\n")
        git("add", ".gitattributes")
        git("commit", "-q", "-m", "attributes")
    for command in ("modify", "optimize"):
        with pytest.raises(DomainError) as error:
            app.execute(command, path)
        assert error.value.code == code
