from dataclasses import asdict

from kh_agent.core.clock import utc_now
from kh_agent.core.enums import Permission
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import RepositoryId, RepositoryRootId, UserId
from kh_agent.identity.service import Identity
from kh_agent.repository.identity import RepositoryIdentity
from kh_agent.store.database import Database, append_event


class Registry:
    def __init__(self, db: Database) -> None:
        self.db = db

    def bootstrap(self, os_principal: str) -> str:
        """Explicit local owner setup. Never derives authority from repository files."""
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
            if rows:
                for row in rows:
                    if row["os_principal"] == os_principal and row["active"] and row["is_admin"]:
                        return row["user_id"]
                raise DomainError(ErrorCode.ACCESS_DENIED, "Store already initialized")
            user_id = str(UserId.new())
            conn.execute("INSERT INTO users VALUES (?, ?, 1, 1)", (user_id, os_principal))
            append_event(
                conn,
                event_type="IDENTITY_REGISTERED",
                aggregate_type="user",
                aggregate_id=user_id,
                repository_id=None,
                user_id=user_id,
                payload={},
            )
            return user_id

    @staticmethod
    def _admin(conn, actor: Identity) -> None:
        row = conn.execute(
            "SELECT active,is_admin FROM users WHERE user_id=?", (actor.user_id,)
        ).fetchone()
        if not row or not row["active"] or not row["is_admin"]:
            raise DomainError(ErrorCode.ACCESS_DENIED)

    def add_user(self, actor: Identity, os_principal: str) -> str:
        if not os_principal.startswith("linux-uid:") or not os_principal[10:].isdigit():
            raise DomainError(ErrorCode.INVALID_INPUT, "Expected Linux UID principal")
        if str(int(os_principal[10:])) != os_principal[10:]:
            raise DomainError(ErrorCode.INVALID_INPUT, "Expected canonical UID")
        with self.db.transaction() as conn:
            self._admin(conn, actor)
            row = conn.execute(
                "SELECT user_id FROM users WHERE os_principal=?", (os_principal,)
            ).fetchone()
            if row:
                return row[0]
            user_id = str(UserId.new())
            conn.execute("INSERT INTO users VALUES (?, ?, 1, 0)", (user_id, os_principal))
            append_event(
                conn,
                event_type="IDENTITY_REGISTERED",
                aggregate_type="user",
                aggregate_id=user_id,
                repository_id=None,
                user_id=actor.user_id,
                payload={"target_user_id": user_id},
            )
            return user_id

    def register(self, actor: Identity, identity: RepositoryIdentity, key: str) -> dict:
        def action(conn):
            self._admin(conn, actor)
            row = conn.execute(
                "SELECT * FROM repositories WHERE common_dir=?", (identity.common_dir,)
            ).fetchone()
            if row and row["common_identity"] != identity.common_identity:
                raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
            repository_id = row["repository_id"] if row else str(RepositoryId.new())
            if not row:
                conn.execute(
                    "INSERT INTO repositories VALUES (?,?,?,?)",
                    (repository_id, identity.common_dir, identity.common_identity, utc_now()),
                )
            root = conn.execute(
                "SELECT * FROM repository_roots WHERE canonical_root=?", (identity.canonical_root,)
            ).fetchone()
            if root:
                self._match(root, identity)
                if root["repository_id"] != repository_id:
                    raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
                return {"repository_id": repository_id, "root_id": root["root_id"]}
            root_id = str(RepositoryRootId.new())
            conn.execute(
                "INSERT INTO repository_roots VALUES (?,?,?,?,?,?)",
                (
                    root_id,
                    repository_id,
                    identity.canonical_root,
                    identity.root_identity,
                    identity.git_dir,
                    identity.git_identity,
                ),
            )
            # Registration is an explicit administrative grant to the registering owner.
            for permission in Permission:
                conn.execute(
                    "INSERT OR IGNORE INTO permissions VALUES (?,?,?)",
                    (actor.user_id, repository_id, permission.value),
                )
            append_event(
                conn,
                event_type="REPOSITORY_REGISTERED",
                aggregate_type="repository",
                aggregate_id=repository_id,
                repository_id=repository_id,
                user_id=actor.user_id,
                payload={"root_id": root_id},
            )
            return {"repository_id": repository_id, "root_id": root_id}

        # Current administration is rechecked even for an idempotent replay.
        with self.db.transaction() as conn:
            self._admin(conn, actor)
        return self.db.operation(
            key,
            {"action": "register", "actor": actor.user_id, "identity": asdict(identity)},
            action,
        )

    @staticmethod
    def _match(root, identity: RepositoryIdentity) -> None:
        if any(
            root[field] != getattr(identity, field)
            for field in ("root_identity", "git_dir", "git_identity")
        ):
            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)

    def lookup(self, identity: RepositoryIdentity) -> str:
        rows = self.db.rows(
            "SELECT rr.*,r.common_dir,r.common_identity FROM repository_roots rr "
            "JOIN repositories r USING(repository_id) WHERE rr.canonical_root=?",
            (identity.canonical_root,),
        )
        if not rows:
            raise DomainError(ErrorCode.REPOSITORY_UNREGISTERED)
        self._match(rows[0], identity)
        if (
            rows[0]["common_dir"] != identity.common_dir
            or rows[0]["common_identity"] != identity.common_identity
        ):
            raise DomainError(ErrorCode.REPOSITORY_IDENTITY_CHANGED)
        return rows[0]["repository_id"]

    def permission(
        self,
        actor: Identity,
        user_id: str,
        repository_id: str,
        permission: Permission,
        *,
        grant: bool,
    ) -> None:
        UserId(user_id)
        RepositoryId(repository_id)
        with self.db.transaction() as conn:
            self._admin(conn, actor)
            if grant:
                conn.execute(
                    "INSERT OR IGNORE INTO permissions VALUES (?,?,?)",
                    (user_id, repository_id, permission.value),
                )
            else:
                conn.execute(
                    "DELETE FROM permissions WHERE user_id=? AND repository_id=? AND permission=?",
                    (user_id, repository_id, permission.value),
                )
            append_event(
                conn,
                event_type="ACL_CHANGED",
                aggregate_type="repository",
                aggregate_id=repository_id,
                repository_id=repository_id,
                user_id=actor.user_id,
                payload={
                    "target_user_id": user_id,
                    "permission": permission.value,
                    "allowed": grant,
                },
            )
