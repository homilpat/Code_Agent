import hashlib
import shutil
import subprocess
import sys

import pytest

from kh_agent.repository.snapshot import SourceFile, SourceSnapshot
from kh_agent.sandbox.container import RootlessContainerBackend
from kh_agent.sandbox.policy import PytestRequest, SandboxProfile, compile_pytest

IMAGE_TAG = "localhost/kh-python-pytest:v1"


def image_id():
    podman = shutil.which("podman")
    if sys.platform != "linux" or not podman:
        return None
    done = subprocess.run(  # noqa: S603 - test discovery of the prebuilt sandbox image
        [podman, "image", "inspect", "--format", "{{.Id}}", IMAGE_TAG],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else None


IMAGE = image_id()
pytestmark = pytest.mark.skipif(
    IMAGE is None, reason="needs Linux rootless podman and the kh-python-pytest image"
)


def snapshot_of(files):
    return SourceSnapshot(
        tuple(
            SourceFile(path.encode(), data.encode(), hashlib.sha256(data.encode()).hexdigest())
            for path, data in files.items()
        ),
        "a" * 64,
        "test-v1",
        (),
        "PARTIAL",
        ("TEST_FIXTURE",),
    )


def run(files, targets=("tests",), timeout=120, **profile):
    backend = RootlessContainerBackend(str(IMAGE), SandboxProfile(**profile))
    return backend, backend.execute(
        compile_pytest(PytestRequest(tuple(targets), timeout)), snapshot_of(files)
    )


def managed_containers(backend):
    listed = backend._runtime(
        "ps", "--all", "--filter", "label=knowledge-hub.managed=true", "--format", "{{.Names}}"
    )
    return listed.stdout.decode().split()


def test_passing_and_failing_suites_are_judged_by_exit_code():
    _, passed = run({"tests/test_ok.py": "def test_ok():\n    assert 1 + 1 == 2\n"})
    assert (passed.status, passed.exit_code, passed.termination_reason) == ("PASS", 0, "EXITED")
    _, failed = run({"tests/test_bad.py": "def test_bad():\n    assert False\n"})
    assert (failed.status, failed.exit_code) == ("FAIL", 1)
    assert passed.attestation_digest and passed.plan_hash


def test_network_source_writes_host_secrets_and_privileges_are_isolated(monkeypatch):
    monkeypatch.setenv("KH_HOST_SECRET_TOKEN", "must-not-leak")
    probe = """
import os, socket
import pytest

def test_isolation():
    assert "KH_HOST_SECRET_TOKEN" not in os.environ
    assert os.getuid() == 65532
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 53), timeout=2)
    with pytest.raises(OSError):
        open("written.txt", "w")
    status = dict(line.split(":", 1) for line in open("/proc/self/status") if ":" in line)
    assert status["CapEff"].strip() == "0000000000000000"
    assert status["NoNewPrivs"].strip() == "1"
    assert status["Seccomp"].strip() == "2"
"""
    _, result = run({"tests/test_isolation.py": probe})
    assert result.status == "PASS", result.output


def test_src_layout_imports_resolve_without_repository_configuration():
    files = {
        "src/pkg/__init__.py": "",
        "src/pkg/core.py": "VALUE = 3\n",
        "tests/test_core.py": "from pkg.core import VALUE\n\n\ndef test_value():\n"
        "    assert VALUE == 3\n",
        "pytest.ini": "[pytest]\naddopts = --this-option-does-not-exist\n",
    }
    _, result = run(files)
    assert result.status == "PASS", result.output


def test_timeout_is_inconclusive_and_the_container_is_removed():
    slow = "import time\n\n\ndef test_slow():\n    time.sleep(60)\n"
    backend, result = run({"tests/test_slow.py": slow}, timeout=5)
    assert (result.status, result.termination_reason) == ("INCONCLUSIVE", "TIMEOUT")
    assert not managed_containers(backend)


def test_memory_limit_fails_the_check():
    hungry = "def test_hungry():\n    block = bytearray(512 * 1024 * 1024)\n    assert block\n"
    _, result = run({"tests/test_hungry.py": hungry}, memory_mib=128)
    assert result.status == "FAIL", result.output
    assert result.termination_reason in ("MEMORY_LIMIT", "MEMORY_LIMIT_SUSPECTED")


def test_output_limit_truncates_and_never_passes():
    noisy = "def test_noisy():\n    print('x' * 4_000_000)\n    assert False\n"
    _, result = run({"tests/test_noisy.py": noisy}, max_output_bytes=65536)
    assert result.output_truncated and len(result.output.encode()) <= 65536
    assert result.status != "PASS"
