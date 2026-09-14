"""Bounded reference metadata parsing, without interpreting repository configuration."""

import re

from kh_agent.core.errors import DomainError, ErrorCode

PACKED_REFS_LIMIT = 4 * 1024 * 1024
OID = re.compile(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def valid_ref(value: bytes) -> bool:
    return (
        value.startswith(b"refs/")
        and not any(byte <= 32 or byte == 127 for byte in value)
        and not any(char in value for char in (b"~", b"^", b":", b"?", b"*", b"[", b"\\"))
        and b".." not in value
        and b"@{" not in value
        and not value.endswith(b".")
        and all(
            part and not part.startswith(b".") and not part.endswith(b".lock")
            for part in value.split(b"/")
        )
    )


def packed_ref(data: bytes, target: bytes) -> bytes | None:
    """Validate the complete file, including duplicates and peeled tag records."""
    if len(data) > PACKED_REFS_LIMIT:
        raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
    seen: set[bytes] = set()
    result = None
    previous_oid = None
    width = None
    for line in data.split(b"\n"):
        if not line:
            previous_oid = None
            continue
        if line.startswith(b"#"):
            previous_oid = None
            continue
        if line.startswith(b"^"):
            if previous_oid is None or not OID.fullmatch(line[1:]) or len(line[1:]) != width:
                raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
            previous_oid = None
            continue
        oid, separator, ref = line.partition(b" ")
        if (
            not separator
            or not OID.fullmatch(oid)
            or not valid_ref(ref)
            or ref in seen
            or (width is not None and len(oid) != width)
        ):
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
        seen.add(ref)
        width = len(oid)
        previous_oid = oid
        if ref == target:
            result = oid
    return result
