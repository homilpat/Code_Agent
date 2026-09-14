from types import SimpleNamespace

import pytest

from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.security import policy as policy_module


class PolicyFileReached(Exception):
    """Raised instead of opening the policy file: the repository checks already passed."""


@pytest.fixture
def linux_loader(monkeypatch):
    def stop(*args, **kwargs):
        raise PolicyFileReached

    # Reach the repository checks on any host: the Linux-only file open is replaced by a sentinel.
    monkeypatch.setattr(policy_module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(policy_module.os, "O_NOFOLLOW", 0, raising=False)
    monkeypatch.setattr(policy_module, "open_no_alias", stop)


def test_deleted_repository_root_is_ignored(tmp_path, linux_loader):
    store = tmp_path / "store"
    store.mkdir()
    healthy = tmp_path / "healthy"
    healthy.mkdir()
    with pytest.raises(PolicyFileReached):
        policy_module.load_policy(store, (tmp_path / "deleted", healthy))


def test_store_inside_repository_is_denied(tmp_path, linux_loader):
    repo = tmp_path / "repo"
    (repo / "store").mkdir(parents=True)
    with pytest.raises(DomainError) as error:
        policy_module.load_policy(repo / "store", (repo,))
    assert error.value.code == ErrorCode.ACCESS_DENIED


def test_store_inside_repository_is_denied_after_deleted_root(tmp_path, linux_loader):
    repo = tmp_path / "repo"
    (repo / "store").mkdir(parents=True)
    with pytest.raises(DomainError) as error:
        policy_module.load_policy(repo / "store", (tmp_path / "deleted", repo))
    assert error.value.code == ErrorCode.ACCESS_DENIED
