import hashlib
import shutil
import subprocess
import sys

import pytest

from kh_agent.core.errors import DomainError
from kh_agent.repository.snapshot import SourceFile, SourceSnapshot
from kh_agent.sandbox.container import RootlessContainerBackend
from kh_agent.sandbox.lsp import LspSession, PythonLanguageClient
from kh_agent.sandbox.policy import (
    LanguageServerRequest,
    PytestRequest,
    compile_language_server,
    compile_pytest,
)

IMAGE_TAG = "localhost/kh-python-pyright:v1"
FILES = {
    "src/pkg/__init__.py": "",
    "src/pkg/core.py": "def helper(value: int) -> int:\n    return value + 1\n",
    "src/pkg/main.py": "from pkg.core import helper\n\n\ndef run() -> int:\n    return helper(2)\n",
    "src/pkg/other.py": "from pkg import core\n\nVALUE = core.helper(3)\n",
    "src/pkg/uses_os.py": "import os\n\nCWD = os.getcwd()\n",
    "src/pkg/broken.py": "def text() -> int:\n    return 'text'\n",
}


def image_id():
    podman = shutil.which("podman")
    if sys.platform != "linux" or not podman:
        return None
    done = subprocess.run(  # noqa: S603 - test discovery of the prebuilt language server image
        [podman, "image", "inspect", "--format", "{{.Id}}", IMAGE_TAG],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else None


IMAGE = image_id()
pytestmark = pytest.mark.skipif(
    IMAGE is None, reason="needs Linux rootless podman and the kh-python-pyright image"
)


def snapshot():
    return SourceSnapshot(
        tuple(
            SourceFile(path.encode(), data.encode(), hashlib.sha256(data.encode()).hexdigest())
            for path, data in FILES.items()
        ),
        "b" * 64,
        "test-v1",
        (),
        "PARTIAL",
        ("TEST_FIXTURE",),
    )


def managed_containers(backend):
    listed = backend._runtime(
        "ps", "--all", "--filter", "label=knowledge-hub.managed=true", "--format", "{{.Names}}"
    )
    return listed.stdout.decode().split()


def test_definition_references_and_diagnostics_come_from_the_sandboxed_server():
    backend = RootlessContainerBackend(str(IMAGE))
    command = compile_language_server(LanguageServerRequest(300))
    with backend.language_server(command, snapshot()) as server:
        session = LspSession(server.stdin, server.stdout, on_failure=server.kill)
        try:
            client = PythonLanguageClient(session, request_timeout=120)
            client.open("src/pkg/main.py", FILES["src/pkg/main.py"])
            definition = client.definition("src/pkg/main.py", 4, 11)
            assert [(item.path, item.start_line, item.start_character) for item in definition] == [
                ("src/pkg/core.py", 0, 4)
            ], server.stderr_tail()
            references = client.references("src/pkg/core.py", 0, 4)
            assert {item.path for item in references} >= {
                "src/pkg/core.py",
                "src/pkg/main.py",
                "src/pkg/other.py",
            }
            client.open("src/pkg/uses_os.py", FILES["src/pkg/uses_os.py"])
            stdlib = client.definition("src/pkg/uses_os.py", 2, 9)
            assert stdlib and all(item.path is None for item in stdlib)
            client.open("src/pkg/broken.py", FILES["src/pkg/broken.py"])
            errors = [
                item for item in client.diagnostics("src/pkg/broken.py") if item.severity == 1
            ]
            assert [(item.line, item.path) for item in errors] == [(1, "src/pkg/broken.py")]
        finally:
            session.close()
    assert not managed_containers(backend)


def test_killed_server_fails_closed_and_templates_cannot_be_mixed():
    backend = RootlessContainerBackend(str(IMAGE))
    command = compile_language_server(LanguageServerRequest(300))
    with backend.language_server(command, snapshot()) as server:
        session = LspSession(server.stdin, server.stdout, on_failure=server.kill)
        server.kill()
        with pytest.raises(DomainError):
            PythonLanguageClient(session, request_timeout=30)
    with pytest.raises(DomainError):
        backend.execute(command, snapshot())
    with (
        pytest.raises(DomainError),
        backend.language_server(compile_pytest(PytestRequest(("tests",))), snapshot()),
    ):
        pass
    assert not managed_containers(backend)
