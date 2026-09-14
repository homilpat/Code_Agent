import re
from pathlib import Path

from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.repository.identity import RepositoryIdentity, is_alias, read_metadata
from kh_agent.repository.refs import PACKED_REFS_LIMIT, packed_ref, valid_ref


class MetadataInspector:
    """Metadata-only status. Never claims object resolution, dirty state or graph freshness."""

    def inspect(self, identity: RepositoryIdentity) -> dict:
        git_dir = Path(identity.git_dir)
        try:
            observed: list[tuple[Path, int, bytes | None]] = []

            def read(path: Path, limit: int = 4096) -> bytes | None:
                try:
                    value = read_metadata(path, limit)
                except FileNotFoundError:
                    value = None
                return value

            def remember(path: Path, limit: int = 4096) -> bytes | None:
                value = read(path, limit)
                observed.append((path, limit, value))
                return value

            head_bytes = remember(git_dir / "HEAD")
            if head_bytes is None:
                raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
            head = head_bytes.decode("utf-8").rstrip("\r\n")
            branch = None
            declared_head_oid = None
            head_state = "UNRESOLVED"
            if head.startswith("ref: refs/heads/"):
                ref = head[5:]
                parts = ref.split("/")
                if not valid_ref(ref.encode("utf-8")):
                    raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
                branch = ref[len("refs/heads/") :]
                ref_path = Path(identity.common_dir)
                for part in parts:
                    ref_path /= part
                    if ref_path.exists() and is_alias(ref_path):
                        raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
                ref_bytes = remember(ref_path)
                if ref_bytes is None:
                    packed = remember(Path(identity.common_dir) / "packed-refs", PACKED_REFS_LIMIT)
                    if packed is not None:
                        ref_bytes = packed_ref(packed, ref.encode("utf-8"))
                if ref_bytes is not None:
                    value = ref_bytes.decode("ascii").rstrip("\r\n")
                    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
                        raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
                    declared_head_oid = value
            elif re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
                head_state = "DETACHED"
                declared_head_oid = head
            else:
                raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
            operations = [
                name
                for name in (
                    "MERGE_HEAD",
                    "CHERRY_PICK_HEAD",
                    "REVERT_HEAD",
                    "rebase-merge",
                    "rebase-apply",
                    "sequencer",
                    "BISECT_LOG",
                )
                if (git_dir / name).exists() or (git_dir / name).is_symlink()
            ]
            # Detect changed/deleted/replaced refs, including creation of a missing loose ref.
            # This is a bounded consistency check, not an atomic repository snapshot.
            if any(read(path, limit) != value for path, limit, value in observed):
                raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED)
        except (OSError, UnicodeError) as exc:
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED) from exc
        return {
            "canonical_repository_root": identity.canonical_root,
            "inspection_scope": "GIT_ADMINISTRATIVE_METADATA_ONLY",
            "branch": branch,
            "declared_head_oid": declared_head_oid,
            "commit_sha": None,
            "head_state": head_state,
            "git_operation_state": "IN_PROGRESS" if operations else "NORMAL",
            "git_operations": operations,
            "working_tree_dirty": None,
            "working_tree_diff_hash": None,
            "graph_freshness": "NOT_AVAILABLE",
            "source_completeness": "NOT_AVAILABLE",
            "mutation_ready": False,
            "local_only_runtime_status": "NOT_AVAILABLE",
        }
