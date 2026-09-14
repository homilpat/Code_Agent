import math
import re
from dataclasses import dataclass

from kh_agent.core.canonical import canonical_hash


@dataclass(frozen=True)
class IngestionPolicy:
    version: str = "ingestion-v1"
    excluded_directories: frozenset[str] = frozenset(
        {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".next",
            "target",
            "build",
            "dist",
            ".knowledge-hub",
        }
    )
    max_entries: int = 10000
    max_file_bytes: int = 256 * 1024
    max_total_bytes: int = 16 * 1024 * 1024
    max_depth: int = 32
    max_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.version or any(
            value <= 0
            for value in (
                self.max_entries,
                self.max_file_bytes,
                self.max_total_bytes,
                self.max_depth,
                self.max_seconds,
            )
        ):
            raise ValueError("Positive ingestion bounds and policy version are required")
        if not math.isfinite(self.max_seconds):
            raise ValueError("Finite timeout required")

    def fingerprint(self) -> str:
        return canonical_hash(
            {
                "version": self.version,
                "excluded_directories": sorted(self.excluded_directories),
                "max_entries": self.max_entries,
                "max_file_bytes": self.max_file_bytes,
                "max_total_bytes": self.max_total_bytes,
                "max_depth": self.max_depth,
                "max_timeout_ms": int(self.max_seconds * 1000),
            },
            "ingestion-policy-v1",
        ).digest


def sensitive_path(name: str) -> bool:
    lower = name.casefold()
    return (
        lower == ".env"
        or lower.startswith(".env.")
        or lower
        in {
            "id_rsa",
            "id_ed25519",
            "credentials",
            "credentials.json",
            "secrets.json",
            "secrets.yaml",
            "secrets.yml",
            ".netrc",
            ".npmrc",
        }
        or lower.endswith((".pem", ".key", ".p12", ".pfx", ".keystore"))
    )


_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(
        rb"(?i)(?:password|secret|api[_-]?key|access[_-]?token)\s*[=:]\s*[\"'][^\"'\r\n]{4,}[\"']"
    ),
)


def sensitive_content(data: bytes) -> bool:
    """Conservative built-in detectors, not a claim of complete secret discovery."""
    return any(pattern.search(data) for pattern in _SECRET_PATTERNS)
