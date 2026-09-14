import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.security.linux_fs import open_no_alias


def physical_identity(path: Path) -> str:
    value = path.stat()
    return f"{value.st_dev}:{value.st_ino}"


def is_alias(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def read_metadata(path: Path, limit: int = 4096) -> bytes:
    """Bounded no-follow administrative reads; never invoke Git/config/hook machinery."""
    if is_alias(path):
        raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = (
        open_no_alias(os.fsencode(path.absolute()), flags)
        if sys.platform == "linux"
        else os.open(path, flags)
    )
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit or info.st_nlink != 1:
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        named = path.lstat()

        def signature(value: os.stat_result, ctime: bool = True) -> tuple:
            fields = (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
            )
            return (*fields, value.st_ctime_ns) if ctime else fields

        # Windows path lookups can report st_ctime_ns a few ms behind the open handle for a
        # recently written file, which made this check fail at random. The handle-vs-path
        # comparison omits ctime there only; Linux, the supported runtime, compares every field.
        path_ctime = sys.platform == "linux"
        if (
            len(data) > limit
            or len(data) != info.st_size
            or signature(info) != signature(after)
            or signature(after, path_ctime) != signature(named, path_ctime)
            or is_alias(path)
        ):
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
        return data


@dataclass(frozen=True)
class RepositoryIdentity:
    canonical_root: str
    root_identity: str
    git_dir: str
    git_identity: str
    common_dir: str
    common_identity: str


class RepositoryIdentityResolver:
    def resolve(self, path: Path) -> RepositoryIdentity:
        try:
            candidate = path.resolve(strict=True)
            if not candidate.is_dir():
                candidate = candidate.parent
            for root in (candidate, *candidate.parents):
                marker = root / ".git"
                if not marker.exists() and not marker.is_symlink():
                    continue
                if is_alias(marker):
                    raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
                if marker.is_dir():
                    git_dir = marker.resolve(strict=True)
                    common_dir = git_dir
                    if (git_dir / "commondir").exists():
                        raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
                else:
                    data = read_metadata(marker)
                    if not data.startswith(b"gitdir: "):
                        raise DomainError(ErrorCode.NOT_A_GIT_REPOSITORY)
                    git_dir = (root / os.fsdecode(data[8:].rstrip(b"\r\n"))).resolve(strict=True)
                    common = read_metadata(git_dir / "commondir")
                    common_dir = (git_dir / os.fsdecode(common.rstrip(b"\r\n"))).resolve(True)
                    # Linked worktree registration must be reciprocal and structurally valid.
                    backlink = read_metadata(git_dir / "gitdir").rstrip(b"\r\n")
                    if (
                        Path(os.fsdecode(backlink)).resolve(True) != marker
                        or git_dir.parent != common_dir / "worktrees"
                    ):
                        raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
                if not git_dir.is_dir() or not (common_dir / "objects").is_dir():
                    raise DomainError(ErrorCode.NOT_A_GIT_REPOSITORY)
                return RepositoryIdentity(
                    str(root),
                    physical_identity(root),
                    str(git_dir),
                    physical_identity(git_dir),
                    str(common_dir),
                    physical_identity(common_dir),
                )
        except (OSError, ValueError, RuntimeError) as exc:
            raise DomainError(ErrorCode.NOT_A_GIT_REPOSITORY) from exc
        raise DomainError(ErrorCode.NOT_A_GIT_REPOSITORY)
