from dataclasses import dataclass

from kh_agent.core.enums import Permission
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.identity.service import Identity
from kh_agent.store.database import Database, append_event

COMMAND_PERMISSIONS = {
    "status": frozenset({Permission.REPOSITORY_VIEW}),
    "explain": frozenset({Permission.CODE_ANALYZE}),
    "impact": frozenset({Permission.CODE_ANALYZE}),
    "modify": frozenset({Permission.CHANGE_PROPOSE}),
    "profile": frozenset({Permission.RUNTIME_ANALYZE}),
    "optimize": frozenset({Permission.CHANGE_PROPOSE, Permission.RUNTIME_ANALYZE}),
    "verify": frozenset({Permission.PATCH_VERIFY}),
    "apply": frozenset({Permission.PATCH_APPROVE, Permission.PATCH_APPLY}),
    "history": frozenset({Permission.HISTORY_VIEW}),
}


# Protected commands are authorized before touching the repository and again after long
# ingestion; the audit event records which of the two checks it was.
CHECK_POINTS = frozenset({"BEFORE_REPOSITORY_ACCESS", "AFTER_SOURCE_INGESTION"})


@dataclass(frozen=True)
class AuthorizedRepository:
    repository_id: str
    user_id: str
    command: str


class AuthorizationService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def authorize(
        self,
        identity: Identity,
        repository_id: str,
        command: str,
        check_point: str = "BEFORE_REPOSITORY_ACCESS",
    ) -> AuthorizedRepository:
        if command not in COMMAND_PERMISSIONS:
            raise DomainError(ErrorCode.INVALID_INPUT, "Unknown command")
        if check_point not in CHECK_POINTS:
            raise DomainError(ErrorCode.INVALID_INPUT, "Unknown authorization check point")
        with self.db.transaction() as conn:
            user = conn.execute(
                "SELECT active FROM users WHERE user_id=?", (identity.user_id,)
            ).fetchone()
            repo = conn.execute(
                "SELECT 1 FROM repositories WHERE repository_id=?", (repository_id,)
            ).fetchone()
            if user is None or repo is None:
                raise DomainError(ErrorCode.ACCESS_DENIED)
            granted = {
                row[0]
                for row in conn.execute(
                    "SELECT permission FROM permissions WHERE user_id=? AND repository_id=?",
                    (identity.user_id, repository_id),
                )
            }
            allowed = bool(user["active"]) and COMMAND_PERMISSIONS[command] <= granted
            append_event(
                conn,
                event_type="ACL_CHECKED",
                aggregate_type="repository",
                aggregate_id=repository_id,
                repository_id=repository_id,
                user_id=identity.user_id,
                payload={"command": command, "allowed": allowed, "check_point": check_point},
            )
        # Denial is raised after commit, so the denial event remains durable.
        if not allowed:
            raise DomainError(ErrorCode.ACCESS_DENIED)
        return AuthorizedRepository(repository_id, identity.user_id, command)
