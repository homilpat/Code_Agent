import hashlib
import re
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

DESIGN = Path(__file__).resolve().parents[2] / "docs" / "ARCHITECTURE_DETAILED_DESIGN_v1.10.md"
DESIGN_TEST_ID = re.compile(
    r"^(M\d\d-(?:UT|IT|SEC|CTX|SNP|BND|GIT|GRF|POT|LNG|PRS)-\d{3}) ", re.MULTILINE
)
REQUIREMENTS = pytest.StashKey[tuple[set[str], dict[str, set[str]], dict[str, set[str]]]]()


def design_test_ids(text: str) -> set[str]:
    return set(DESIGN_TEST_ID.findall(text))


def requirement_coverage(
    marks: list[tuple[str, tuple, dict]], defined: set[str]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Map design test IDs to tests; an unknown or empty marker is a usage error."""
    covered: dict[str, set[str]] = {}
    partial: dict[str, set[str]] = {}
    for test, ids, options in marks:
        unknown = set(ids) - defined
        if not ids or unknown or set(options) - {"partial"}:
            raise ValueError(f"{test}: invalid req marker {sorted(unknown) or ids or options}")
        target = partial if options.get("partial") else covered
        for test_id in ids:
            target.setdefault(test_id, set()).add(test)
    return covered, partial


def pytest_addoption(parser):
    parser.addoption("--req-report", action="store_true", help="Summarize design test ID coverage.")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "req(*ids, partial=False): design test IDs this test verifies"
    )


def pytest_collection_modifyitems(config, items):
    defined = design_test_ids(DESIGN.read_text(encoding="utf-8"))
    marks = [
        (item.nodeid.split("[")[0], mark.args, mark.kwargs)
        for item in items
        for mark in item.iter_markers("req")
    ]
    try:
        covered, partial = requirement_coverage(marks, defined)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from None
    config.stash[REQUIREMENTS] = (defined, covered, partial)


def pytest_terminal_summary(terminalreporter, config):
    if not config.getoption("--req-report") or REQUIREMENTS not in config.stash:
        return
    defined, covered, partial = config.stash[REQUIREMENTS]
    only_partial = set(partial) - set(covered)
    missing = defined - set(covered) - set(partial)
    write = terminalreporter.write_line
    terminalreporter.write_sep("-", "design test ID coverage")
    write(
        f"defined {len(defined)} | covered {len(covered)} | partial only {len(only_partial)}"
        f" | uncovered {len(missing)}"
    )
    for group in sorted({test_id.rsplit("-", 1)[0] for test_id in defined}):
        ids = {test_id for test_id in defined if test_id.startswith(group + "-")}
        write(
            f"  {group}: {len(ids & set(covered))} covered, "
            f"{len(ids & only_partial)} partial, {len(ids & missing)} uncovered of {len(ids)}"
        )
    write("partial only: " + ", ".join(sorted(only_partial)))
    write("uncovered: " + ", ".join(sorted(missing)))


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
