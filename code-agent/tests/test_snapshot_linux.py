import os
import sys

import pytest

from kh_agent.core.errors import DomainError
from kh_agent.repository.identity import RepositoryIdentityResolver
from kh_agent.repository.snapshot import SourceScanner
from kh_agent.security.ingestion import IngestionPolicy
from kh_agent.security.linux_fs import open_no_alias

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux openat2 source boundary")


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


def test_enumeration_quota_fails_closed(environment):
    (environment.repo / "a.py").write_text("pass")
    with pytest.raises(DomainError):
        SourceScanner(IngestionPolicy(max_entries=1)).scan(
            RepositoryIdentityResolver().resolve(environment.repo)
        )


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
