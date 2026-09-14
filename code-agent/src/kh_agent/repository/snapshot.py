import hashlib
import os
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from kh_agent.core.canonical import canonical_hash, encode_path
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.repository.identity import RepositoryIdentity
from kh_agent.security.ingestion import IngestionPolicy, sensitive_content, sensitive_path
from kh_agent.security.linux_fs import open_no_alias


@dataclass(frozen=True)
class SourceFile:
    path: bytes
    content: bytes
    content_hash: str


@dataclass(frozen=True)
class SourceSnapshot:
    files: tuple[SourceFile, ...]
    snapshot_hash: str
    policy_version: str
    exclusions: tuple[dict, ...]
    completeness: str
    limitations: tuple[str, ...]


def mounted_paths() -> set[bytes]:
    try:
        lines = Path("/proc/self/mountinfo").read_bytes().splitlines()
        result = set()
        for line in lines:
            mount = line.split(b" - ", 1)[0].split()[4]
            for escaped, value in (
                (b"\\040", b" "),
                (b"\\011", b"\t"),
                (b"\\012", b"\n"),
                (b"\\134", b"\\"),
            ):
                mount = mount.replace(escaped, value)
            result.add(mount)
        return result
    except (OSError, IndexError) as exc:
        raise DomainError(
            ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Cannot establish mount boundaries"
        ) from exc


class SourceScanner:
    """Bounded, descriptor-relative Linux traversal without following repository aliases.

    Files are read only after path classification, then classified again by content.
    Snapshot is explicitly PARTIAL until safe index/object inspection is integrated.
    No source is executed or persisted here.
    """

    def __init__(self, policy: IngestionPolicy | None = None) -> None:
        self.policy = policy or IngestionPolicy()

    def scan(self, repository: RepositoryIdentity) -> SourceSnapshot:
        if sys.platform != "linux":
            raise DomainError(
                ErrorCode.UNSUPPORTED_PLATFORM, "Secure source ingestion requires Linux"
            )
        policy = self.policy
        root = os.fsencode(repository.canonical_root)
        root_fd = open_no_alias(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(root_fd)
        if f"{info.st_dev}:{info.st_ino}" != repository.root_identity:
            os.close(root_fd)
            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
        try:
            mounts = mounted_paths()
            files: list[SourceFile] = []
            exclusions: list[dict] = []
            manifest: list[dict] = []
            start = time.monotonic()
            visited = total = 0

            def excluded(path: bytes, reason: str) -> None:
                item = {"path": encode_path(path), "reason": reason}
                exclusions.append(item)
                manifest.append(item)

            def visit(fd: int, prefix: bytes, depth: int) -> None:
                nonlocal visited, total
                if depth > policy.max_depth:
                    excluded(prefix, "DEPTH_LIMIT")
                    return
                with os.scandir(fd) as entries:
                    names = []
                    for entry in entries:
                        visited += 1
                        if (
                            visited > policy.max_entries
                            or time.monotonic() - start > policy.max_seconds
                        ):
                            raise DomainError(
                                ErrorCode.SAFE_GIT_POLICY_BLOCKED,
                                "Source enumeration quota exceeded",
                            )
                        names.append(os.fsencode(entry.name))
                for name in sorted(names):
                    relative = prefix + b"/" + name if prefix else name
                    if time.monotonic() - start > policy.max_seconds:
                        raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Snapshot timeout")
                    entry_info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISLNK(entry_info.st_mode):
                        excluded(relative, "SYMLINK")
                        continue
                    if root + b"/" + relative in mounts or entry_info.st_dev != info.st_dev:
                        excluded(relative, "MOUNT_BOUNDARY")
                        continue
                    decoded = os.fsdecode(name)
                    if decoded in policy.excluded_directories:
                        excluded(relative, "POLICY_EXCLUDED")
                        continue
                    if sensitive_path(decoded):
                        excluded(relative, "SENSITIVE_PATH")
                        continue
                    if stat.S_ISDIR(entry_info.st_mode):
                        child_fd = open_no_alias(
                            relative, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, root_fd=root_fd
                        )
                        try:
                            opened = os.fstat(child_fd)
                            if (opened.st_dev, opened.st_ino) != (
                                entry_info.st_dev,
                                entry_info.st_ino,
                            ):
                                raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
                            try:
                                os.stat(b".git", dir_fd=child_fd, follow_symlinks=False)
                            except FileNotFoundError:
                                visit(child_fd, relative, depth + 1)
                            else:
                                excluded(relative, "NESTED_REPOSITORY")
                        finally:
                            os.close(child_fd)
                        continue
                    if not stat.S_ISREG(entry_info.st_mode) or entry_info.st_nlink != 1:
                        excluded(relative, "SPECIAL_FILE_OR_HARDLINK")
                        continue
                    if entry_info.st_size > policy.max_file_bytes:
                        excluded(relative, "FILE_SIZE_LIMIT")
                        continue
                    if total + entry_info.st_size > policy.max_total_bytes:
                        raise DomainError(
                            ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Source byte quota exceeded"
                        )
                    file_fd = open_no_alias(
                        relative, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, root_fd=root_fd
                    )
                    with os.fdopen(file_fd, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        if (
                            not stat.S_ISREG(before.st_mode)
                            or before.st_nlink != 1
                            or (before.st_dev, before.st_ino)
                            != (entry_info.st_dev, entry_info.st_ino)
                        ):
                            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
                        data = stream.read(policy.max_file_bytes + 1)
                        after = os.fstat(stream.fileno())
                    final = os.stat(name, dir_fd=fd, follow_symlinks=False)

                    def signature(value):
                        return (
                            value.st_dev,
                            value.st_ino,
                            value.st_size,
                            value.st_mtime_ns,
                            value.st_ctime_ns,
                            value.st_mode,
                            value.st_nlink,
                        )

                    if signature(before) != signature(after) or signature(after) != signature(
                        final
                    ):
                        raise DomainError(
                            ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Source changed during read"
                        )
                    total += len(data)
                    if len(data) > policy.max_file_bytes or total > policy.max_total_bytes:
                        raise DomainError(
                            ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Source byte quota exceeded"
                        )
                    if sensitive_content(data):
                        excluded(relative, "SENSITIVE_CONTENT")
                        continue
                    digest = hashlib.sha256(data).hexdigest()
                    manifest.append(
                        {
                            "path": encode_path(relative),
                            "content_hash": digest,
                            "mode": stat.S_IMODE(after.st_mode),
                            "size": len(data),
                        }
                    )
                    if relative.endswith(b".py"):
                        files.append(SourceFile(relative, data, digest))

            visit(root_fd, b"", 0)
            if mounted_paths() != mounts:
                raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Mount topology changed")
            snapshot_hash = canonical_hash(
                {"manifest": manifest, "policy": policy.fingerprint()}, "source-manifest-v1"
            ).digest
            return SourceSnapshot(
                tuple(files),
                snapshot_hash,
                policy.version,
                tuple(exclusions),
                "PARTIAL",
                ("GIT_INDEX_AND_OBJECTS_NOT_INSPECTED", "POINT_IN_TIME_ATOMICITY_NOT_PROVEN"),
            )
        except OSError as exc:
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Source read unavailable") from exc
        finally:
            os.close(root_fd)
