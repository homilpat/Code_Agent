import hashlib

import pytest

from kh_agent.analysis.python_graph import build_graph, explain, impact, inspect_python
from kh_agent.application import Application
from kh_agent.core.enums import Permission
from kh_agent.core.errors import DomainError
from kh_agent.repository.snapshot import SourceFile, SourceSnapshot
from kh_agent.security.ingestion import IngestionPolicy, sensitive_content, sensitive_path


def snapshot_of(mapping):
    return SourceSnapshot(
        tuple(
            SourceFile(path.encode(), data, hashlib.sha256(data).hexdigest())
            for path, data in mapping.items()
        ),
        "a" * 64,
        "test-v1",
        (),
        "PARTIAL",
        ("TEST_FIXTURE",),
    )


@pytest.mark.req("M02-LNG-001", partial=True)
def test_ast_extracts_definitions_and_never_executes(tmp_path):
    marker = tmp_path / "must-not-exist"
    data = (
        f"open({str(marker)!r}, 'w').write('executed')\n"
        "import os\nclass Service:\n    async def run(self):\n        os.getcwd()\n"
    ).encode()
    result = inspect_python(data)
    assert not marker.exists()
    assert [d["symbol"] for d in result["definitions"]] == ["Service", "Service.run"]
    assert result["definitions"][1]["async"] is True
    assert result["calls"][-1]["callee_expression"] == "os.getcwd"
    assert result["calls"][-1]["resolution"] == "UNRESOLVED_STATIC_EXPRESSION"


def test_decorator_call_belongs_to_surrounding_scope():
    result = inspect_python(b"@decorate()\ndef run():\n    work()\n")
    by_name = {item["callee_expression"]: item["caller"] for item in result["calls"]}
    assert by_name == {"decorate": "<module>", "work": "run"}


@pytest.mark.req("M02-PRS-001")
def test_parse_failure_is_unavailable_without_raw_error_source():
    result = inspect_python(b"def invalid(secret password here")
    assert result["coverage"] == "UNAVAILABLE"
    assert "password" not in str(result)


@pytest.mark.req("M02-PRS-002")
def test_static_parser_bounds_input_before_building_ast():
    assert inspect_python(b"a" * 262145)["reason"] == "PYTHON_INPUT_LIMIT"
    assert inspect_python(b"a=1\n" * 5000)["reason"] == "PYTHON_TOKEN_LIMIT"


@pytest.mark.req("M02-GRF-004", partial=True)
def test_graph_hash_changes_with_source_and_policy():
    graph = build_graph(snapshot_of({"main.py": b"def first(): pass"}))
    other = build_graph(snapshot_of({"main.py": b"def second(): pass"}))
    assert graph["graph_hash"] != other["graph_hash"]
    assert IngestionPolicy().fingerprint() != IngestionPolicy(max_entries=1).fingerprint()


def test_explain_and_import_candidates_are_not_runtime_truth():
    graph = build_graph(
        snapshot_of({"lib.py": b"def run(): pass", "main.py": b"import lib\nlib.run()"})
    )
    result = explain(graph, "lib.py")
    assert result["module"]["definitions"][0]["symbol"] == "run"
    changed = impact(graph, "lib.py")
    assert len(changed["import_candidates"]) == 1
    assert changed["risk"] == "NOT_AVAILABLE" and changed["impact_complete"] is False
    for target in ("../secret.py", "/etc/secret.py", "absent.py"):
        with pytest.raises(DomainError):
            explain(graph, target)


def test_sensitive_path_and_content_classification():
    for name in (".env", ".ENV.production", "id_rsa", "private.pem", "secrets.yaml"):
        assert sensitive_path(name)
    assert sensitive_content(b'API_KEY = "example-secret-value"')
    assert sensitive_content(b"-----BEGIN PRIVATE KEY-----")
    assert not sensitive_content(b"def add(a, b): return a + b")


@pytest.mark.req("M01-IT-005")
def test_explain_is_authorized_before_scan_and_after_scan(environment):
    env = environment

    class RevokingScanner:
        def scan(self, repository):
            env.registry.permission(
                env.actor,
                env.actor.user_id,
                env.repository_id,
                Permission.CODE_ANALYZE,
                grant=False,
            )
            return snapshot_of({"lib.py": b"def run(): pass"})

    with pytest.raises(DomainError):
        Application(env.db, scanner=RevokingScanner()).execute("explain", env.repo, "lib.py")
    assert not env.db.rows("SELECT * FROM graph_snapshots")

    class ForbiddenScanner:
        def scan(self, repository):
            pytest.fail("Source read before ACL")

    with pytest.raises(DomainError):
        Application(env.db, scanner=ForbiddenScanner()).execute("explain", env.repo, "lib.py")


@pytest.mark.req("M02-SNP-010", partial=True)
def test_graph_persistence_and_audit_are_atomic(environment):
    env = environment

    class Scanner:
        def scan(self, repository):
            return snapshot_of({"lib.py": b"def run(): pass"})

    app = Application(env.db, scanner=Scanner())
    result = app.execute("explain", env.repo, "lib.py")
    assert result["graph_id"] == app.execute("explain", env.repo, "lib.py")["graph_id"]
    assert len(env.db.rows("SELECT * FROM graph_snapshots")) == 1
    stored = env.db.rows("SELECT graph_json FROM graph_snapshots")[0][0]
    assert "def run(): pass" not in stored
