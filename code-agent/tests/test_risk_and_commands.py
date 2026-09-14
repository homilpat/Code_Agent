from dataclasses import replace

import pytest

from kh_agent.analysis.risk import FactorEvidence, FactorRule, RiskPolicy, score_risk
from kh_agent.core.errors import DomainError
from kh_agent.sandbox.policy import PytestRequest, compile_pytest, docker_plan


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
