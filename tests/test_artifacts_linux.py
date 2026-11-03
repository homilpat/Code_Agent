import sys
from dataclasses import replace

import pytest

from kh_agent.core.enums import Classification
from kh_agent.core.errors import DomainError
from kh_agent.store.artifacts import FileArtifacts

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux artifact durability/security"
)


def test_durable_roundtrip_and_corruption(tmp_path):
    root = tmp_path / "artifacts"
    store = FileArtifacts(root)
    try:
        artifact = store.write(b"patch bytes", "test-v1")
        assert store.read(artifact) == b"patch bytes"
        assert (root / artifact.relative_path).stat().st_mode & 0o777 == 0o600
        assert store.orphan_names({artifact.relative_path}) == []
        (root / artifact.relative_path).write_bytes(b"tampered")
        with pytest.raises(DomainError):
            store.read(artifact)
    finally:
        store.close()


def test_protected_content_path_escape_and_symlink_blocked(tmp_path):
    root = tmp_path / "artifacts"
    store = FileArtifacts(root)
    try:
        with pytest.raises(DomainError):
            store.write(b"secret", "v1", Classification.PROTECTED)
        artifact = store.write(b"content", "v1")
        with pytest.raises(DomainError):
            store.read(replace(artifact, relative_path="../outside"))
        path = root / artifact.relative_path
        path.unlink()
        outside = tmp_path / "outside"
        outside.write_bytes(b"content")
        path.symlink_to(outside)
        with pytest.raises(DomainError):
            store.read(artifact)
    finally:
        store.close()
