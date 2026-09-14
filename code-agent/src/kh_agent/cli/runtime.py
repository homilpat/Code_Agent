import os
import stat
import sys
from pathlib import Path

from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.repository.identity import is_alias


def require_linux_store(root: Path) -> Path:
    if sys.platform != "linux":
        raise DomainError(
            ErrorCode.UNSUPPORTED_PLATFORM,
            "Stateful commands require WSL2/Linux; Windows supports development tests",
        )
    # No network/DrvFS authority store. Inspect the actual mount type, not just /mnt names.
    canonical = root.expanduser().absolute()
    for part in reversed((canonical, *canonical.parents)):
        if part.exists() and is_alias(part):
            raise DomainError(ErrorCode.ACCESS_DENIED, "Store paths must not contain aliases")
    mount_type = None
    longest = -1
    try:
        lines = Path("/proc/self/mountinfo").read_text("utf-8").splitlines()
        for line in lines:
            left, right = line.split(" - ", 1)
            mount = left.split()[4]
            for escaped, literal in (
                ("\\040", " "),
                ("\\011", "\t"),
                ("\\012", "\n"),
                ("\\134", "\\"),
            ):
                mount = mount.replace(escaped, literal)
            if canonical.is_relative_to(Path(mount)) and len(mount) > longest:
                longest, mount_type = len(mount), right.split()[0]
    except (OSError, ValueError, IndexError) as exc:
        raise DomainError(ErrorCode.ACCESS_DENIED, "Cannot establish store filesystem") from exc
    if mount_type not in {"ext4", "xfs", "btrfs"}:
        raise DomainError(
            ErrorCode.UNSUPPORTED_PLATFORM,
            "Authority store requires a local Linux ext4/xfs/btrfs filesystem",
        )
    canonical.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = canonical.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise DomainError(ErrorCode.ACCESS_DENIED, "Store must be owned by this UID with mode 0700")
    return canonical
