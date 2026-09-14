import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from kh_agent.core.errors import DomainError, ErrorCode


def _validate(value: Any, depth: int = 0) -> None:
    if depth > 64:
        raise ValueError("Canonical object exceeds depth limit")
    if value is None or type(value) in (str, bool):
        if isinstance(value, str):
            value.encode("utf-8", "strict")
        return
    if type(value) is int and -(2**63) <= value < 2**63:
        return
    if type(value) is list:
        for item in value:
            _validate(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for key, item in value.items():
            _validate(key, depth + 1)
            _validate(item, depth + 1)
        return
    raise ValueError("Canonical values must be JSON primitives; floats are unsupported")


def canonical_bytes(value: Any, schema_version: str) -> bytes:
    """kh-json-v1: UTF-8, sorted keys, no whitespace, no float/Unicode coercion."""
    if not schema_version or len(schema_version) > 100:
        raise ValueError("A bounded nonempty schema version is required")
    envelope = {"canonical_version": "kh-json-v1", "schema_version": schema_version, "value": value}
    _validate(envelope)
    return json.dumps(
        envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True)
class ContentHash:
    digest: str
    schema_version: str
    algorithm: str = "SHA-256"

    def __post_init__(self) -> None:
        if (
            self.algorithm != "SHA-256"
            or len(self.digest) != 64
            or any(c not in "0123456789abcdef" for c in self.digest)
            or not self.schema_version
        ):
            raise ValueError("Invalid versioned SHA-256 hash")


def canonical_hash(value: Any, schema_version: str) -> ContentHash:
    return ContentHash(
        hashlib.sha256(canonical_bytes(value, schema_version)).hexdigest(), schema_version
    )


def encode_path(raw: bytes) -> str:
    """Keep filesystem byte identity; never casefold or normalize Unicode."""
    if not raw or raw.startswith(b"/") or b"\x00" in raw:
        raise DomainError(ErrorCode.INVALID_INPUT, "Expected relative path bytes")
    if any(part in (b"", b".", b"..") for part in raw.split(b"/")):
        raise DomainError(ErrorCode.INVALID_INPUT, "Unsafe relative path")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_path(encoded: str) -> bytes:
    try:
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        if encode_path(raw) != encoded:
            raise ValueError("Noncanonical path")
        return raw
    except (ValueError, UnicodeError) as exc:
        raise DomainError(ErrorCode.INVALID_INPUT, "Invalid encoded path") from exc
