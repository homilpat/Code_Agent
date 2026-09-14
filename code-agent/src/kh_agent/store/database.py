import json
import os
import sqlite3
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from kh_agent.core.canonical import canonical_hash
from kh_agent.core.clock import utc_now
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import AuditEventId


class Database:
    """All writers serialize here; mandatory event and state writes share a transaction."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path, *, timeout: float = 2.0) -> None:
        if not 0 < timeout <= 30:
            raise ValueError("Database timeout must be bounded")
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise DomainError(ErrorCode.ACCESS_DENIED, "Database symlink is forbidden")
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DomainError(ErrorCode.ACCESS_DENIED, "Unsafe database file identity")
        if hasattr(os, "geteuid") and (
            info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise DomainError(ErrorCode.ACCESS_DENIED, "Database must be owner-only")
        self.connection = sqlite3.connect(
            path, timeout=timeout, isolation_level=None, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys=ON")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, self.SCHEMA_VERSION):
                raise DomainError(ErrorCode.SCHEMA_VERSION_UNSUPPORTED)
            mode = self.connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode != "wal":
                raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
            if version == 0:
                schema = files("kh_agent.store").joinpath("schema.sql").read_text("utf-8")
                # executescript otherwise commits implicitly: include the transaction itself.
                self.connection.executescript("BEGIN IMMEDIATE;\n" + schema + "\nCOMMIT;")
        except (sqlite3.Error, DomainError) as exc:
            self.connection.close()
            if isinstance(exc, DomainError):
                raise
            raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED) from exc

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                yield self.connection
                self.connection.execute("COMMIT")
            except BaseException as exc:
                if self.connection.in_transaction:
                    self.connection.rollback()
                if isinstance(exc, (sqlite3.Error, OSError)):
                    raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED) from exc
                raise

    def operation(
        self,
        key: str,
        request: dict[str, Any],
        action: Callable[[sqlite3.Connection], dict[str, Any]],
    ) -> dict[str, Any]:
        if not key or len(key) > 200:
            raise DomainError(ErrorCode.INVALID_INPUT, "Idempotency key required")
        fingerprint = canonical_hash(request, "store-operation-v1").digest
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM operations WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise DomainError(ErrorCode.IDEMPOTENCY_CONFLICT)
                return json.loads(existing["result_json"])
            result = action(conn)
            conn.execute(
                "INSERT INTO operations VALUES (?, ?, ?)",
                (key, fingerprint, json.dumps(result, sort_keys=True)),
            )
            return result

    def rows(self, sql: str, parameters: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return self.connection.execute(sql, parameters).fetchall()
            except sqlite3.Error as exc:
                raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED) from exc


# Only deterministic metadata is admitted; raw source/prompt/credentials have no field.
AUDIT_FIELDS = frozenset(
    {
        "graph_hash",
        "source_snapshot_hash",
        "command",
        "allowed",
        "permission",
        "revision",
        "from",
        "to",
        "reason_code",
        "patch_id",
        "patch_hash",
        "request_intent_id",
        "request_hash",
        "artifact_id",
        "final_diff_hash",
        "verification_result_id",
        "verification_basis_id",
        "basis_hash",
        "root_id",
        "target_user_id",
        "request_type",
    }
)


def append_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    repository_id: str | None,
    user_id: str | None,
    payload: dict[str, Any],
) -> str:
    if not payload.keys() <= AUDIT_FIELDS:
        raise DomainError(ErrorCode.INVALID_INPUT, "Audit payload contains unsupported fields")
    if any(type(value) not in (str, int, bool, type(None)) for value in payload.values()):
        raise DomainError(ErrorCode.INVALID_INPUT, "Audit metadata must be scalar")
    if any(isinstance(value, str) and len(value) > 256 for value in payload.values()):
        raise DomainError(ErrorCode.INVALID_INPUT, "Audit metadata exceeds field limit")
    event_id = str(AuditEventId.new())
    conn.execute(
        "INSERT INTO audit_events(event_id,aggregate_type,aggregate_id,event_type,"
        "repository_id,user_id,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            event_id,
            aggregate_type,
            aggregate_id,
            event_type,
            repository_id,
            user_id,
            json.dumps(payload, sort_keys=True, ensure_ascii=True),
            utc_now(),
        ),
    )
    return event_id
