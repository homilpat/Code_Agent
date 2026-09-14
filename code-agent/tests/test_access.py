import json
from dataclasses import replace

import pytest

from kh_agent.access.service import AuthorizationService
from kh_agent.application import Application
from kh_agent.core.enums import Permission
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.identity.service import IdentityService
from kh_agent.repository.identity import RepositoryIdentityResolver


def test_invalid_session_never_falls_back(environment):
    service = IdentityService(environment.db)
    assert service.resolve().user_id == environment.actor.user_id
    for credential in ("invalid-secret", ""):
        with pytest.raises(DomainError) as error:
            service.resolve(credential)
        assert error.value.code == ErrorCode.SESSION_INVALID
        assert "invalid-secret" not in str(error.value)


def test_environment_username_cannot_impersonate(environment, monkeypatch):
    monkeypatch.setenv("USER", "admin")
    monkeypatch.setenv("USERNAME", "admin")
    monkeypatch.setattr("kh_agent.identity.service.current_os_principal", lambda: "linux-uid:9999")
    with pytest.raises(DomainError) as error:
        IdentityService(environment.db).resolve()
    assert error.value.code == ErrorCode.IDENTITY_UNRESOLVED


def test_denied_acl_is_audited_without_metadata_inspection(environment):
    env = environment
    env.registry.permission(
        env.actor, env.actor.user_id, env.repository_id, Permission.REPOSITORY_VIEW, grant=False
    )

    class ForbiddenInspector:
        def inspect(self, identity):
            pytest.fail("Protected metadata inspected before ACL")

    with pytest.raises(DomainError) as error:
        Application(env.db, inspector=ForbiddenInspector()).execute("status", env.repo)
    assert error.value.code == ErrorCode.ACCESS_DENIED
    last = env.db.rows("SELECT payload_json FROM audit_events ORDER BY sequence DESC LIMIT 1")[0]
    assert json.loads(last[0]) == {"command": "status", "allowed": False}


def test_current_acl_is_checked_for_history_and_apply(environment):
    env = environment
    auth = AuthorizationService(env.db)
    auth.authorize(env.actor, env.repository_id, "apply")
    for command, permission in (
        ("apply", Permission.PATCH_APPLY),
        ("history", Permission.HISTORY_VIEW),
    ):
        env.registry.permission(
            env.actor, env.actor.user_id, env.repository_id, permission, grant=False
        )
        with pytest.raises(DomainError) as error:
            Application(env.db).execute(command, env.repo)
        assert error.value.code == ErrorCode.ACCESS_DENIED


def test_identity_before_discovery(environment, monkeypatch):
    class ForbiddenResolver:
        def resolve(self, path):
            pytest.fail("Repository inspected before identity")

    monkeypatch.setattr("kh_agent.identity.service.current_os_principal", lambda: "linux-uid:9999")
    with pytest.raises(DomainError):
        Application(environment.db, resolver=ForbiddenResolver()).execute(
            "status", environment.repo
        )


def test_stable_registration_and_replacement_detection(environment):
    env = environment
    resolver = RepositoryIdentityResolver()
    physical = resolver.resolve(env.repo / ".git" / "..")
    repeat = env.registry.register(env.actor, physical, "register-again")
    assert repeat["repository_id"] == env.repository_id
    assert len(env.db.rows("SELECT * FROM repositories")) == 1
    with pytest.raises(DomainError) as error:
        env.registry.lookup(replace(physical, root_identity="different-inode"))
    assert error.value.code == ErrorCode.REPOSITORY_IDENTITY_CHANGED


def test_admin_has_no_implicit_repository_access_after_revocation(environment):
    env = environment
    env.registry.permission(
        env.actor, env.actor.user_id, env.repository_id, Permission.CODE_ANALYZE, grant=False
    )
    with pytest.raises(DomainError):
        AuthorizationService(env.db).authorize(env.actor, env.repository_id, "explain")


def test_metadata_status_does_not_claim_validated_source(environment):
    status = Application(environment.db).execute("status", environment.repo)
    assert status["branch"] == "main"
    assert status["declared_head_oid"] == "a" * 40
    assert status["commit_sha"] is None and status["working_tree_dirty"] is None
    assert status["mutation_ready"] is False


def test_nested_repository_does_not_inherit_parent_acl(environment):
    from conftest import make_repository

    nested = make_repository(environment.repo / "nested")
    with pytest.raises(DomainError) as error:
        Application(environment.db).execute("status", nested)
    assert error.value.code == ErrorCode.REPOSITORY_UNREGISTERED
