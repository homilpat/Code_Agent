import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kh_agent.core.enums import Classification
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import ArtifactId
from kh_agent.security.linux_fs import open_no_alias


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    relative_path: str
    content_hash: str
    size: int
    classification: str
    schema_version: str


class ArtifactBackend(Protocol):
    def write(
        self,
        data: bytes,
        schema_version: str,
        classification: Classification = Classification.NORMAL,
    ) -> Artifact: ...
    def read(self, artifact: Artifact) -> bytes: ...


class FileArtifacts:
    """Linux owner-private, no-follow, fsync-before-metadata artifact storage.

    The trusted root is outside repositories. Only an open directory descriptor is
    used for file operations. Protected bytes fail closed until key-store wiring exists.
    """

    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, root: Path) -> None:
        if sys.platform != "linux":
            raise DomainError(
                ErrorCode.UNSUPPORTED_PLATFORM, "Durable artifact storage requires Linux"
            )
        root.mkdir(mode=0o700, exist_ok=True)
        self._fd = open_no_alias(
            os.fsencode(root.absolute()), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        info = os.fstat(self._fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            self.close()
            raise DomainError(ErrorCode.ACCESS_DENIED, "Artifact directory must be owner-only")
        os.fsync(self._fd)
        parent_fd = open_no_alias(os.fsencode(root.parent.absolute()), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def write(
        self,
        data: bytes,
        schema_version: str,
        classification: Classification = Classification.NORMAL,
    ) -> Artifact:
        if classification != Classification.NORMAL:
            raise DomainError(ErrorCode.PROTECTED_STORAGE_UNAVAILABLE)
        if not schema_version or len(data) > self.MAX_BYTES:
            raise DomainError(ErrorCode.INVALID_INPUT, "Invalid artifact size or schema")
        artifact_id = str(ArtifactId.new())
        temp_name = artifact_id + ".tmp"
        final_name = artifact_id + ".bin"
        try:
            fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self._fd,
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # UUID names plus trusted owner-only directory prevent attacker replacement.
            os.rename(temp_name, final_name, src_dir_fd=self._fd, dst_dir_fd=self._fd)
            os.fsync(self._fd)
        except OSError as exc:
            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED) from exc
        return Artifact(
            artifact_id,
            final_name,
            hashlib.sha256(data).hexdigest(),
            len(data),
            classification.value,
            schema_version,
        )

    def read(self, artifact: Artifact) -> bytes:
        if artifact.classification != Classification.NORMAL:
            raise DomainError(ErrorCode.PROTECTED_STORAGE_UNAVAILABLE)
        try:
            ArtifactId(artifact.artifact_id)
            if (
                artifact.relative_path != artifact.artifact_id + ".bin"
                or not 0 <= artifact.size <= self.MAX_BYTES
            ):
                raise ValueError("Invalid artifact reference")
            fd = os.open(artifact.relative_path, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._fd)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != os.geteuid()
                    or info.st_size != artifact.size
                    or stat.S_IMODE(info.st_mode) != 0o600
                ):
                    raise ValueError("Unsafe artifact identity")
                data = stream.read(self.MAX_BYTES + 1)
            if (
                len(data) != artifact.size
                or hashlib.sha256(data).hexdigest() != artifact.content_hash
            ):
                raise ValueError("Artifact integrity mismatch")
            return data
        except (OSError, ValueError) as exc:
            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED) from exc

    def orphan_names(self, referenced: set[str]) -> list[str]:
        """Report, never automatically delete files during authority recovery."""
        return sorted(name for name in os.listdir(self._fd) if name not in referenced)
