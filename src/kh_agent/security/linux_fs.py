import ctypes
import os
import platform
import sys

from kh_agent.core.errors import DomainError, ErrorCode


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64), ("resolve", ctypes.c_uint64)]


def open_no_alias(path: bytes, flags: int, *, root_fd: int | None = None) -> int:
    """Kernel-enforced resolution; unsupported kernels never fall back to open().

    ABI: Linux include/uapi/linux/openat2.h and asm-generic/unistd.h.
    Relative child paths cannot escape the authorized root, follow any symlink,
    or cross a mount point, including a same-device bind mount.
    """
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise DomainError(ErrorCode.UNSUPPORTED_PLATFORM, "openat2 requires Linux x86_64/aarch64")
    if b"\0" in path or not path:
        raise DomainError(ErrorCode.INVALID_INPUT)
    resolve = 0x02 | 0x04
    if root_fd is not None:
        resolve |= 0x01 | 0x08
    how = _OpenHow(flags | os.O_CLOEXEC, 0, resolve)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    fd = libc.syscall(
        ctypes.c_long(437),
        ctypes.c_int(-100 if root_fd is None else root_fd),
        ctypes.c_char_p(path),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if fd < 0:
        raise DomainError(
            ErrorCode.SAFE_GIT_POLICY_BLOCKED,
            "Kernel rejected path resolution or openat2 is unavailable",
        )
    return int(fd)
