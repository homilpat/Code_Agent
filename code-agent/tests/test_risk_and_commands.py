from dataclasses import replace

import pytest

from kh_agent.analysis.risk import FactorEvidence, FactorRule, RiskPolicy, score_risk
from kh_agent.core.errors import DomainError
from kh_agent.sandbox.policy import (
    LanguageServerRequest,
    PytestRequest,
    compile_language_server,
    compile_pytest,
    container_plan,
)


def docker_plan(command, **options):
    return container_plan(
        command, runtime="docker", apparmor_profile="knowledge-hub-verification-v1", **options
    )


def policy():
    return RiskPolicy(
        "risk-test-v1",
        "threshold-test-v1",
        (
            FactorRule("callers", 30, "COUNT", 10),
            FactorRule("coverage", 30, "INVERSE_PERCENT"),
            FactorRule("security", 40, "BOOLEAN"),
        ),
    )


def test_missing_evidence_is_not_zero_and_expands_verification():
    result = score_risk(policy(), {}, phase="PRELIMINARY", basis_hash="a" * 64)
    assert result["score"] is None
    assert result["score_lower_bound"] == 0 and result["score_upper_bound"] == 100
    assert result["risk_level"] == "HIGH" and result["broaden_verification"] is True
    assert set(result["missing_evidence"]) == {"callers", "coverage", "security"}


def test_versioned_deterministic_scoring_and_final_binding():
    evidence = {
        "callers": FactorEvidence(10, "graph-ref"),
        "coverage": FactorEvidence(100, "coverage-ref"),
        "security": FactorEvidence(True, "authorized-sensitive-exception-ref"),
    }
    result = score_risk(
        policy(), evidence, phase="FINAL", basis_hash="a" * 64, canonical_change_set_complete=True
    )
    assert result["score"] == 70 and result["risk_level"] == "HIGH"
    changed = score_risk(
        replace(policy(), rule_version="risk-test-v2"),
        evidence,
        phase="FINAL",
        basis_hash="a" * 64,
        canonical_change_set_complete=True,
    )
    assert changed["risk_hash"] != result["risk_hash"]
    with pytest.raises(DomainError):
        score_risk(policy(), evidence, phase="FINAL", basis_hash="a" * 64)


def test_available_value_without_evidence_reference_is_missing():
    result = score_risk(
        policy(),
        {"security": FactorEvidence(False, None)},
        phase="PRELIMINARY",
        basis_hash="a" * 64,
    )
    assert "security" in result["missing_evidence"]


@pytest.mark.parametrize(
    "target",
    [
        "../outside",
        "--override-ini",
        "tests;curl",
        "$(curl)",
        "/etc/passwd",
        "tests/test.py::case",
        ".git/config",
    ],
)
def test_command_injection_options_and_escaping_blocked(target):
    with pytest.raises(DomainError):
        compile_pytest(PytestRequest((target,)))


def test_command_registry_does_not_inherit_host_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore=tests")
    command = compile_pytest(PytestRequest(("tests/test_app.py",)))
    assert command.argv[-2:] == ("--", "tests/test_app.py")
    assert "OPENAI_API_KEY" not in dict(command.environment)
    assert "PYTEST_ADDOPTS" not in dict(command.environment)
    assert dict(command.environment)["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_sandbox_plan_has_no_host_or_network_execution_authority():
    command = compile_pytest(PytestRequest(("tests",)))
    plan = docker_plan(
        command,
        image="internal/test@sha256:" + "a" * 64,
        source_view="/trusted/source",
        trusted_config="/trusted/pytest.ini",
        container_name="kh-test",
    )
    argv = plan["argv"]
    for required in (
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--user=65532:65532",
    ):
        assert required in argv
    assert "--entrypoint" in argv and "--privileged" not in argv
    assert "docker.sock" not in str(argv)
    assert plan["execution_available"] is False
    with pytest.raises(DomainError):
        docker_plan(
            command,
            image="python:latest",
            source_view="/source",
            trusted_config="/config",
            container_name="kh-test",
        )
    with pytest.raises(DomainError):
        docker_plan(
            command,
            image="internal/test@sha256:" + "a" * 64,
            source_view="/source,readonly=false",
            trusted_config="/config",
            container_name="kh-test",
        )


def test_podman_plan_uses_runtime_syntax_and_adds_apparmor_only_when_attested():
    command = compile_pytest(PytestRequest(("tests",)))
    assert command.argv[:3] == ("/usr/local/bin/python", "-I", "-B")
    assert "--rootdir=/workspace/src" in command.argv and "no:cacheprovider" in command.argv
    options = dict(
        image="sha256:" + "b" * 64,
        source_view="/private/src",
        trusted_config="/private/pytest.ini",
        container_name="kh-abc",
    )
    argv = container_plan(command, runtime="podman", **options)["argv"]
    assert argv[0] == "podman" and "--security-opt=no-new-privileges" in argv
    assert "type=bind,src=/private/src,dst=/workspace/src,ro=true" in argv
    assert not any("apparmor" in item for item in argv) and "--rm" not in argv
    assert not any("nr_inodes" in item for item in argv)
    assert any("nr_inodes=16384" in item for item in docker_plan(command, **options)["argv"])
    for runtime, lsm in (("runc", None), ("podman", "Bad Profile")):
        with pytest.raises(DomainError):
            container_plan(command, runtime=runtime, apparmor_profile=lsm, **options)


def test_language_server_template_is_interactive_isolated_and_cannot_be_forged():
    command = compile_language_server(LanguageServerRequest(300))
    options = dict(
        image="sha256:" + "b" * 64,
        source_view="/private/src",
        trusted_config="/private/pytest.ini",
        container_name="kh-lsp",
    )
    plan = container_plan(command, runtime="podman", **options)
    assert plan["interactive"] is True and "--interactive" in plan["argv"]
    assert "--network=none" in plan["argv"] and "--cap-drop=ALL" in plan["argv"]
    pytest_plan = container_plan(
        compile_pytest(PytestRequest(("tests",))), runtime="podman", **options
    )
    assert pytest_plan["interactive"] is False and "--interactive" not in pytest_plan["argv"]
    for forged in (
        replace(command, argv=("/usr/local/bin/node", "-e", "require('child_process')")),
        replace(command, timeout_seconds=99_999),
        replace(command, template_id="shell"),
        replace(command, environment=(("NODE_OPTIONS", "--require=/workspace/src/x.js"),)),
    ):
        with pytest.raises(DomainError):
            container_plan(forged, runtime="podman", **options)
    with pytest.raises(DomainError):
        compile_language_server(LanguageServerRequest(0))


def attested_info():
    return {
        "version": {"Version": "4.9.3"},
        "host": {
            "cgroupVersion": "v2",
            "cgroupControllers": ["cpu", "memory", "pids"],
            "security": {"rootless": True, "seccompEnabled": True, "apparmorEnabled": False},
            "ociRuntime": {"name": "crun"},
        },
    }


@pytest.mark.parametrize(
    "missing, change",
    [
        ("ROOTLESS", lambda info: info["host"]["security"].update(rootless=False)),
        ("CGROUP_V2", lambda info: info["host"].update(cgroupVersion="v1")),
        ("CGROUP_CONTROLLERS", lambda info: info["host"].update(cgroupControllers=["cpu"])),
        ("SECCOMP", lambda info: info["host"]["security"].update(seccompEnabled=False)),
    ],
)
def test_runtime_attestation_requires_rootless_limits_and_seccomp(missing, change):
    from kh_agent.sandbox.container import attestation_from_info

    attested = attestation_from_info("/usr/bin/podman", attested_info())
    assert attested.capabilities["lsm"] == "NONE"
    assert attested.capabilities["network_mode"] == "NONE"
    assert attested.capabilities["secret_inheritance"] == "NONE"  # noqa: S105 - not a credential
    broken = attested_info()
    change(broken)
    with pytest.raises(DomainError) as error:
        attestation_from_info("/usr/bin/podman", broken)
    assert missing in error.value.message


def test_forged_compiled_command_cannot_add_credentials_or_shell():
    command = compile_pytest(PytestRequest(("tests",)))
    for forged in (
        replace(command, environment=(("SECRET", "credential"),)),
        replace(command, argv=("/bin/sh", "-c", "curl attacker", "--", "tests")),
    ):
        with pytest.raises(DomainError):
            docker_plan(
                forged,
                image="internal/test@sha256:" + "a" * 64,
                source_view="/trusted/source",
                trusted_config="/trusted/config",
                container_name="kh-test",
            )
