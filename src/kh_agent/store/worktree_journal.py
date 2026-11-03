"""Durable prewrite and completion evidence for a single worktree file replacement.

An unfinished attempt is never assumed to have failed: the rename may have occurred
before a process crash. No automatic retry or rollback is offered.
"""

import hashlib
import json
import os
import stat
from collections.abc import Callable

from kh_agent.core.canonical import ContentHash, encode_path
from kh_agent.core.enums import Permission
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import CommandRequestId
from kh_agent.patch.file_writer import replace_source_file
from kh_agent.patch.canonical import target_path
from kh_agent.repository.identity import RepositoryIdentity
from kh_agent.repository.snapshot import SourceFile
from kh_agent.security.ingestion import sensitive_content, sensitive_path
from kh_agent.security.linux_fs import open_no_alias
from kh_agent.store.database import Database, append_event, verify_audit_chain


class WorktreeWriteJournal:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _pending(conn, repository_id: str) -> dict[str, dict]:
        attempts: dict[str, dict] = {}
        seen: set[str] = set()
        for event in conn.execute(
            "SELECT event_type,payload_json FROM audit_events WHERE repository_id=? "
            "AND event_type IN ('WORKTREE_WRITE_PREPARED','WORKTREE_WRITE_FINISHED',"
            "'WORKTREE_WRITE_RECONCILED') "
            "ORDER BY sequence",
            (repository_id,),
        ):
            try:
                payload = json.loads(event["payload_json"])
                attempt_id = payload["attempt_id"]
                CommandRequestId(attempt_id)
            except (ValueError, KeyError, TypeError) as exc:
                raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED) from exc
            if event["event_type"] == "WORKTREE_WRITE_PREPARED":
                required = {
                    "attempt_id", "path_hash", "before_sha256", "after_sha256",
                    "source_snapshot_hash", "target_state_digest",
                }
                proof = {"candidate_hash", "test_plan_hash", "test_attestation_digest"}
                if attempt_id in seen or payload.keys() not in (required, required | proof):
                    raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                for field in payload.keys() - {"attempt_id"}:
                    try:
                        ContentHash(payload[field], "worktree-write-v1")
                    except (TypeError, ValueError) as exc:
                        raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED) from exc
                attempts[attempt_id] = payload
                seen.add(attempt_id)
            elif event["event_type"] == "WORKTREE_WRITE_FINISHED":
                if (
                    attempt_id not in attempts
                    or payload.keys() != {"attempt_id", "after_sha256"}
                    or payload["after_sha256"] != attempts[attempt_id]["after_sha256"]
                ):
                    raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                del attempts[attempt_id]
            else:
                if (
                    attempt_id not in attempts
                    or payload.keys() != {"attempt_id", "after_sha256", "reason_code"}
                    or payload["reason_code"] not in ("ORIGINAL_BYTES", "REPLACEMENT_BYTES")
                    or payload["after_sha256"] != attempts[attempt_id][
                        "before_sha256" if payload["reason_code"] == "ORIGINAL_BYTES"
                        else "after_sha256"
                    ]
                ):
                    raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
                del attempts[attempt_id]
        return attempts

    def pending(self, repository_id: str) -> list[str]:
        with self.db.transaction() as conn:
            verify_audit_chain(conn)
            return sorted(self._pending(conn, repository_id))

    def prepare(
        self,
        repository_id: str,
        user_id: str,
        *,
        path: bytes,
        before_sha256: str,
        after_sha256: str,
        source_snapshot_hash: str,
        target_state_digest: str,
        candidate_hash: str | None = None,
        test_plan_hash: str | None = None,
        test_attestation_digest: str | None = None,
    ) -> str:
        proof = (candidate_hash, test_plan_hash, test_attestation_digest)
        if any(value is None for value in proof) and any(value is not None for value in proof):
            raise DomainError(ErrorCode.INVALID_INPUT, "Incomplete test binding")
        for value in (
            before_sha256, after_sha256, source_snapshot_hash, target_state_digest,
            *(item for item in proof if item is not None),
        ):
            try:
                ContentHash(value, "worktree-write-v1")
            except ValueError as exc:
                raise DomainError(ErrorCode.INVALID_INPUT, "Invalid write binding") from exc
        if type(path) is not bytes or not path or len(path) > 1024:
            raise DomainError(ErrorCode.INVALID_INPUT)
        encode_path(path)
        with self.db.transaction() as conn:
            verify_audit_chain(conn)
            if self._pending(conn, repository_id):
                raise DomainError(
                    ErrorCode.CRITICAL_PERSISTENCE_FAILED, "Unresolved worktree write"
                )
            attempt_id = str(CommandRequestId.new())
            append_event(
                conn,
                event_type="WORKTREE_WRITE_PREPARED",
                aggregate_type="repository",
                aggregate_id=repository_id,
                repository_id=repository_id,
                user_id=user_id,
                payload={
                    "attempt_id": attempt_id,
                    "path_hash": hashlib.sha256(path).hexdigest(),
                    "before_sha256": before_sha256,
                    "after_sha256": after_sha256,
                    "source_snapshot_hash": source_snapshot_hash,
                    "target_state_digest": target_state_digest,
                    **({
                        "candidate_hash": candidate_hash,
                        "test_plan_hash": test_plan_hash,
                        "test_attestation_digest": test_attestation_digest,
                    } if candidate_hash is not None else {}),
                },
            )
            return attempt_id

    def finish(self, repository_id: str, user_id: str, attempt_id: str) -> None:
        try:
            CommandRequestId(attempt_id)
        except ValueError as exc:
            raise DomainError(ErrorCode.INVALID_INPUT) from exc
        with self.db.transaction() as conn:
            verify_audit_chain(conn)
            pending = self._pending(conn, repository_id)
            bound = pending.get(attempt_id)
            if bound is None:
                raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
            append_event(
                conn,
                event_type="WORKTREE_WRITE_FINISHED",
                aggregate_type="repository",
                aggregate_id=repository_id,
                repository_id=repository_id,
                user_id=user_id,
                payload={"attempt_id": attempt_id, "after_sha256": bound["after_sha256"]},
            )

    def reconcile(
        self,
        repository_id: str,
        user_id: str,
        attempt_id: str,
        repository: RepositoryIdentity,
        path: bytes,
    ) -> str:
        """Observe an unfinished write; never infer verification or approval from it."""
        try:
            CommandRequestId(attempt_id)
        except ValueError as exc:
            raise DomainError(ErrorCode.INVALID_INPUT) from exc
        if not isinstance(repository, RepositoryIdentity) or type(path) is not bytes:
            raise DomainError(ErrorCode.INVALID_INPUT)
        encode_path(path)
        with self.db.transaction() as conn:
            verify_audit_chain(conn)
            pending = self._pending(conn, repository_id)
            bound = pending.get(attempt_id)
            if bound is None or hashlib.sha256(path).hexdigest() != bound["path_hash"]:
                raise DomainError(ErrorCode.INVALID_INPUT, "Wrong pending file")
            user = conn.execute("SELECT active FROM users WHERE user_id=?", (user_id,)).fetchone()
            allowed = conn.execute(
                "SELECT 1 FROM permissions WHERE user_id=? AND repository_id=? AND permission=?",
                (user_id, repository_id, Permission.PATCH_APPLY.value),
            ).fetchone()
            if not user or not user["active"] or not allowed:
                raise DomainError(ErrorCode.ACCESS_DENIED)
            root_fd = open_no_alias(
                os.fsencode(repository.canonical_root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                root = os.fstat(root_fd)
                if f"{root.st_dev}:{root.st_ino}" != repository.root_identity:
                    raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
                fd = open_no_alias(path, os.O_RDONLY | os.O_NOFOLLOW, root_fd=root_fd)
                with os.fdopen(fd, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                        raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED)
                    data = stream.read(256 * 1024 + 1)
                    after = os.fstat(stream.fileno())
                if (
                    len(data) > 256 * 1024
                    or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                        before.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                     after.st_ctime_ns)
                ):
                    raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED)
                current_fd = open_no_alias(path, os.O_RDONLY | os.O_NOFOLLOW, root_fd=root_fd)
                try:
                    current = os.fstat(current_fd)
                    if (
                        current.st_dev, current.st_ino, current.st_size,
                        current.st_mtime_ns, current.st_ctime_ns, current.st_nlink,
                    ) != (
                        after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns, after.st_nlink,
                    ):
                        raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED)
                finally:
                    os.close(current_fd)
                observed = hashlib.sha256(data).hexdigest()
            finally:
                os.close(root_fd)
            if observed == bound["before_sha256"]:
                reason = "ORIGINAL_BYTES"
            elif observed == bound["after_sha256"]:
                reason = "REPLACEMENT_BYTES"
            else:
                raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "File has unknown bytes")
            append_event(
                conn,
                event_type="WORKTREE_WRITE_RECONCILED",
                aggregate_type="repository",
                aggregate_id=repository_id,
                repository_id=repository_id,
                user_id=user_id,
                payload={"attempt_id": attempt_id, "after_sha256": observed, "reason_code": reason},
            )
            return reason


def journaled_replace_source_file(
    journal: WorktreeWriteJournal,
    repository_id: str,
    user_id: str,
    repository: RepositoryIdentity,
    source: SourceFile,
    content: bytes,
    *,
    source_snapshot_hash: str,
    target_state_digest: str,
    precommit: Callable[[], None],
    postcommit: Callable[[], None] | None = None,
    candidate_hash: str | None = None,
    test_plan_hash: str | None = None,
    test_attestation_digest: str | None = None,
) -> str:
    """Internal primitive; caller must establish current ACL and a formal apply basis.

    If any step after prepare fails, the pending intent blocks later journaled writes.
    A trusted operator must inspect and reconcile it; retrying blindly is unsafe.
    """
    if type(content) is not bytes or not isinstance(source, SourceFile):
        raise DomainError(ErrorCode.INVALID_INPUT)
    try:
        if target_path(source.path.decode("utf-8", "strict")) != source.path:
            raise DomainError(ErrorCode.INVALID_INPUT)
    except UnicodeDecodeError as exc:
        raise DomainError(ErrorCode.INVALID_INPUT) from exc
    if (
        not source.path.endswith(b".py")
        or any(sensitive_path(part) for part in source.path.decode("utf-8").split("/"))
        or len(content) > 256 * 1024
        or b"\0" in content
        or sensitive_content(content)
        or content == source.content
        or source.content_hash != hashlib.sha256(source.content).hexdigest()
    ):
        raise DomainError(ErrorCode.INVALID_INPUT)
    expected = hashlib.sha256(content).hexdigest()
    attempt_id = journal.prepare(
        repository_id,
        user_id,
        path=source.path,
        before_sha256=source.content_hash,
        after_sha256=expected,
        source_snapshot_hash=source_snapshot_hash,
        target_state_digest=target_state_digest,
        candidate_hash=candidate_hash,
        test_plan_hash=test_plan_hash,
        test_attestation_digest=test_attestation_digest,
    )
    actual = replace_source_file(repository, source, content, precommit=precommit)
    if actual != expected:
        raise DomainError(ErrorCode.CRITICAL_PERSISTENCE_FAILED)
    if postcommit is not None:
        postcommit()
    journal.finish(repository_id, user_id, attempt_id)
    return actual
