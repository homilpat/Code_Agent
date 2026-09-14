import os
from dataclasses import dataclass
from typing import Protocol

from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import UserId
from kh_agent.store.database import Database


@dataclass(frozen=True)
class Identity:
    user_id: str
    source: str
    session_reference: str | None = None


class SessionProvider(Protocol):
    def resolve(self, credential: str) -> Identity: ...


def current_os_principal() -> str:
    if not hasattr(os, "geteuid"):
        raise DomainError(ErrorCode.UNSUPPORTED_PLATFORM, "OS mapping requires Linux UID")
    # Never trust USER, LOGNAME, USERNAME or caller-supplied display names.
    return f"linux-uid:{os.geteuid()}"


class IdentityService:
    def __init__(self, db: Database, session_provider: SessionProvider | None = None) -> None:
        self.db = db
        self.session_provider = session_provider

    def resolve(self, credential: str | None = None) -> Identity:
        if credential is not None:
            # An invalid/present token must never silently fall back to weaker OS identity.
            if not credential or self.session_provider is None:
                raise DomainError(ErrorCode.SESSION_INVALID)
            try:
                identity = self.session_provider.resolve(credential)
                UserId(identity.user_id)
            except Exception as exc:
                raise DomainError(ErrorCode.SESSION_INVALID) from exc
            rows = self.db.rows("SELECT active FROM users WHERE user_id=?", (identity.user_id,))
            if not rows or not rows[0]["active"]:
                raise DomainError(ErrorCode.SESSION_INVALID)
            return identity
        rows = self.db.rows(
            "SELECT user_id FROM users WHERE os_principal=? AND active=1", (current_os_principal(),)
        )
        if not rows:
            raise DomainError(ErrorCode.IDENTITY_UNRESOLVED)
        return Identity(rows[0]["user_id"], "OS_MAPPING")
