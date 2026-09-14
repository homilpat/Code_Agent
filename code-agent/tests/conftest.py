import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from kh_agent.core.enums import Classification
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import ArtifactId
from kh_agent.identity.service import Identity
from kh_agent.repository.identity import RepositoryIdentityResolver
from kh_agent.store.artifacts import Artifact
from kh_agent.store.database import Database
from kh_agent.store.patches import PatchStore
from kh_agent.store.registry import Registry


class MemoryArtifacts:
    """Explicit test double. Production only wires Linux FileArtifacts."""

    def __init__(self):
        self.data = {}

    def write(self, data, schema_version, classification=Classification.NORMAL):
        if classification != Classification.NORMAL:
            raise DomainError(ErrorCode.PROTECTED_STORAGE_UNAVAILABLE)
        artifact_id = str(ArtifactId.new())
        self.data[artifact_id] = data
        return Artifact(
            artifact_id,
            artifact_id + ".bin",
            hashlib.sha256(data).hexdigest(),
            len(data),
            classification.value,
            schema_version,
        )

    def read(self, artifact):
        data = self.data.get(artifact.artifact_id)
        if data is None or hashlib.sha256(data).hexdigest() != artifact.content_hash:
            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
        return data


def make_repository(path: Path) -> Path:
    (path / ".git" / "objects").mkdir(parents=True)
    (path / ".git" / "refs" / "heads").mkdir(parents=True)
    (path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (path / ".git" / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    return path


@dataclass
class Environment:
    db: Database
    registry: Registry
    actor: Identity
    repository_id: str
    repo: Path
    artifacts: MemoryArtifacts
    patches: PatchStore


@pytest.fixture
def environment(tmp_path, monkeypatch):
    db = Database(tmp_path / "store" / "test.db")
    registry = Registry(db)
    actor = Identity(registry.bootstrap("linux-uid:1000"), "OS_MAPPING")
    monkeypatch.setattr("kh_agent.identity.service.current_os_principal", lambda: "linux-uid:1000")
    repo = make_repository(tmp_path / "repo")
    identity = RepositoryIdentityResolver().resolve(repo)
    repository_id = registry.register(actor, identity, "register")["repository_id"]
    artifacts = MemoryArtifacts()
    yield Environment(
        db, registry, actor, repository_id, repo, artifacts, PatchStore(db, artifacts)
    )
    db.close()
