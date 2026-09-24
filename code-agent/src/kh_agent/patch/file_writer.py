"""One-file worktree replacement primitive for a future trusted apply orchestrator.

This is not an approval gate or a CLI: the caller must establish a complete base,
durable intent, current ACL and verification before invoking it. Filesystem checks
cannot make an unrelated Git process participate in the same atomic transaction.
"""

import hashlib
import os
import secrets
import stat
from collections.abc import Callable

from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.patch.canonical import target_path
from kh_agent.repository.identity import RepositoryIdentity
from kh_agent.repository.snapshot import SourceFile
from kh_agent.security.ingestion import sensitive_content, sensitive_path
from kh_agent.security.linux_fs import open_no_alias


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def replace_source_file(
    repository: RepositoryIdentity,
    source: SourceFile,
    content: bytes,
    *,
    precommit: Callable[[], None],
) -> str:
    """Write a checked replacement via a same-directory, fsynced rename.

    ``precommit`` belongs to the trusted orchestrator: it rechecks ACL, Git and
    source snapshot before staging the replacement. The original inode remains
    intact until that check succeeds. No automatic rollback or approval is implied.
    """
    if not isinstance(repository, RepositoryIdentity) or not isinstance(source, SourceFile):
        raise DomainError(ErrorCode.INVALID_INPUT)
    path = source.path
    try:
        decoded = path.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise DomainError(ErrorCode.INVALID_INPUT, "Only UTF-8 Python paths can be written") from exc
    if (
        target_path(decoded) != path
        or not path.endswith(b".py")
        or any(sensitive_path(part) for part in decoded.split("/"))
    ):
        raise DomainError(ErrorCode.INVALID_INPUT, "Only one existing Python file is supported")
    if (
        type(content) is not bytes
        or len(content) > 256 * 1024
        or b"\0" in content
        or sensitive_content(content)
        or content == source.content
        or hashlib.sha256(source.content).hexdigest() != source.content_hash
    ):
        raise DomainError(ErrorCode.INVALID_INPUT, "Replacement content or baseline is invalid")

    root_fd = open_no_alias(
        os.fsencode(repository.canonical_root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    try:
        root = os.fstat(root_fd)
        if f"{root.st_dev}:{root.st_ino}" != repository.root_identity:
            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
        parent_path, _, name = path.rpartition(b"/")
        parent_fd = (
            open_no_alias(
                parent_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, root_fd=root_fd
            )
            if parent_path
            else os.dup(root_fd)
        )
        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_dev != root.st_dev
                or stat.S_IMODE(before.st_mode) not in (0o644, 0o755)
            ):
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Unsafe file identity")
            fd = open_no_alias(path, os.O_RDONLY | os.O_NOFOLLOW, root_fd=root_fd)
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if _signature(opened) != _signature(before):
                    raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "File changed before read")
                actual = stream.read(len(source.content) + 1)
                after = os.fstat(stream.fileno())
            if (
                _signature(after) != _signature(opened)
                or actual != source.content
                or _signature(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
                != _signature(before)
            ):
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "File changed before apply")
            # Recheck before creating a visible temporary file in the worktree.
            precommit()
            temporary = b".kh-replacement-" + secrets.token_hex(16).encode("ascii")
            temp_fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=parent_fd,
            )
            try:
                with os.fdopen(temp_fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fchmod(stream.fileno(), stat.S_IMODE(before.st_mode))
                    os.fsync(stream.fileno())
                if _signature(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) != _signature(
                    before
                ):
                    raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "File changed before rename")
                root_now_fd = open_no_alias(
                    os.fsencode(repository.canonical_root),
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                )
                try:
                    root_now = os.fstat(root_now_fd)
                    if f"{root_now.st_dev}:{root_now.st_ino}" != repository.root_identity:
                        raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
                finally:
                    os.close(root_now_fd)
                current_parent_fd = (
                    open_no_alias(
                        parent_path,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        root_fd=root_fd,
                    )
                    if parent_path else os.dup(root_fd)
                )
                try:
                    current = os.fstat(current_parent_fd)
                    parent = os.fstat(parent_fd)
                    if (current.st_dev, current.st_ino) != (parent.st_dev, parent.st_ino):
                        raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
                finally:
                    os.close(current_parent_fd)
                os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                os.fsync(parent_fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            return hashlib.sha256(content).hexdigest()
        finally:
            os.close(parent_fd)
    except OSError as exc:
        raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Worktree replacement failed") from exc
    finally:
        os.close(root_fd)
