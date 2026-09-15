import os
import sys

import pytest

from kh_agent.core.canonical import decode_path, encode_path
from kh_agent.core.errors import DomainError
from kh_agent.repository.identity import RepositoryIdentityResolver
from kh_agent.repository.snapshot import SourceScanner
from kh_agent.security.ingestion import IngestionPolicy
from kh_agent.security.linux_fs import open_no_alias

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux openat2 source boundary")


@pytest.mark.req("M02-BND-001", "M02-BND-003", "M02-BND-009", "M02-SNP-006", "M02-SNP-007")
def test_scanner_excludes_sensitive_alias_nested_and_hardlinked_files(environment):
    from conftest import make_repository

    repo = environment.repo
    (repo / "safe.py").write_text("def safe(): pass\n")
    (repo / ".env").write_text("PASSWORD=do-not-ingest")
    (repo / "sensitive.py").write_text('API_KEY = "do-not-ingest"\n')
    outside = repo.parent / "outside.py"
    outside.write_text("def outside(): pass\n")
    (repo / "alias.py").symlink_to(outside)
    os.link(outside, repo / "hard.py")
    nested = make_repository(repo / "nested")
    (nested / "nested.py").write_text("def nested(): pass")
    scanner = SourceScanner()
    identity = RepositoryIdentityResolver().resolve(repo)
    result = scanner.scan(identity)
    assert [file.path for file in result.files] == [b"safe.py"]
    reasons = {item["reason"] for item in result.exclusions}
    assert {
        "SENSITIVE_PATH",
        "SENSITIVE_CONTENT",
        "SYMLINK",
        "NESTED_REPOSITORY",
        "SPECIAL_FILE_OR_HARDLINK",
    } <= reasons
    assert result.snapshot_hash == scanner.scan(identity).snapshot_hash
    (repo / "safe.py").write_text("def changed(): pass\n")
    assert result.snapshot_hash != scanner.scan(identity).snapshot_hash


@pytest.mark.req("M02-SNP-009", "M02-PRS-004", partial=True)
def test_enumeration_quota_fails_closed(environment):
    (environment.repo / "a.py").write_text("pass")
    with pytest.raises(DomainError):
        SourceScanner(IngestionPolicy(max_entries=1)).scan(
            RepositoryIdentityResolver().resolve(environment.repo)
        )


@pytest.mark.req("M02-BND-001")
def test_openat2_cannot_escape_root_or_follow_symlink(tmp_path):
    (tmp_path / "inside").mkdir()
    (tmp_path / "secret").write_text("secret")
    (tmp_path / "inside" / "link").symlink_to(tmp_path / "secret")
    fd = os.open(tmp_path / "inside", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for path in (b"../secret", b"link", os.fsencode(tmp_path / "secret")):
            with pytest.raises(DomainError):
                open_no_alias(path, os.O_RDONLY, root_fd=fd)
    finally:
        os.close(fd)


def scan(repo):
    return SourceScanner().scan(RepositoryIdentityResolver().resolve(repo))


@pytest.mark.req("M02-BND-010")
@pytest.mark.req("M02-BND-002", partial=True)  # symlinks are excluded, not reclassified
def test_symlinks_inside_the_repository_are_never_followed(environment):
    repo = environment.repo
    (repo / "real.py").write_text("def real(): pass\n")
    (repo / ".env").write_text("PASSWORD=do-not-ingest")
    (repo / "inside_alias.py").symlink_to(repo / "real.py")
    (repo / "config.py").symlink_to(repo / ".env")
    result = scan(repo)
    assert [file.path for file in result.files] == [b"real.py"]
    reasons = {decode_path(item["path"]): item["reason"] for item in result.exclusions}
    assert reasons[b"inside_alias.py"] == "SYMLINK"
    assert reasons[b"config.py"] == "SYMLINK"
    assert all(b"do-not-ingest" not in file.content for file in result.files)


@pytest.mark.req("M02-BND-004")
def test_directory_with_a_git_file_is_a_repository_boundary(environment):
    repo = environment.repo
    linked = repo / "linked"
    linked.mkdir()
    (linked / ".git").write_text("gitdir: /elsewhere/.git/worktrees/linked\n")
    (linked / "inside.py").write_text("def inside(): pass\n")
    result = scan(repo)
    assert not any(file.path.startswith(b"linked/") for file in result.files)
    assert {"path": encode_path(b"linked"), "reason": "NESTED_REPOSITORY"} in result.exclusions


@pytest.mark.req("M02-SNP-005")
def test_policy_excluded_build_output_does_not_change_source_scope(environment):
    repo = environment.repo
    (repo / "app.py").write_text("def app(): pass\n")
    before = scan(repo)
    (repo / "build").mkdir()
    (repo / "build" / "generated.py").write_text("def generated(): pass\n")
    after = scan(repo)
    assert [file.path for file in after.files] == [file.path for file in before.files]
    assert {"path": encode_path(b"build"), "reason": "POLICY_EXCLUDED"} in after.exclusions
