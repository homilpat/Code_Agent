import base64
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass

from kh_agent.access.gates import MutationContext, require_normal_mutation
from kh_agent.core.canonical import ContentHash, canonical_hash, decode_path, encode_path
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import RepositoryId, RequestIntentId
from kh_agent.security.ingestion import sensitive_content, sensitive_path


@dataclass(frozen=True)
class BaselineFile:
    content: bytes
    mode: int = 0o644

    def __post_init__(self) -> None:
        if type(self.content) is not bytes or self.mode not in (0o644, 0o755):
            raise DomainError(
                ErrorCode.INVALID_INPUT, "Only regular files with supported modes are allowed"
            )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class ProposalBase:
    repository_id: str
    request_intent_id: str
    branch: str
    commit_sha: str
    source_snapshot_hash: str
    preliminary_risk_reference: str
    source_completeness: str
    dirty: bool | None
    head_state: str = "NORMAL"
    git_operation_state: str = "NORMAL"

    def require(self) -> None:
        RepositoryId(self.repository_id)
        RequestIntentId(self.request_intent_id)
        ContentHash(self.source_snapshot_hash, "source-snapshot-v1")
        ContentHash(self.preliminary_risk_reference, "preliminary-risk-v1")
        if self.source_completeness != "COMPLETE" or not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", self.commit_sha
        ):
            raise DomainError(
                ErrorCode.REPOSITORY_STATE_BLOCKED, "Complete resolved source base required"
            )
        require_normal_mutation(
            MutationContext(
                self.head_state, self.branch, self.commit_sha, self.git_operation_state, self.dirty
            )
        )


@dataclass(frozen=True)
class ChangeEntry:
    path: str  # Reversible base64url of POSIX relative path bytes.
    operation: str
    mode_before: int | None
    mode_after: int | None
    hash_before: str | None
    hash_after: str | None
    content_after_base64: str | None

    def __post_init__(self) -> None:
        decode_path(self.path)
        if self.operation not in ("create", "modify", "delete"):
            raise DomainError(ErrorCode.INVALID_INPUT, "Unsupported operation")
        has_before = self.operation != "create"
        has_after = self.operation != "delete"
        for present, mode, digest in (
            (has_before, self.mode_before, self.hash_before),
            (has_after, self.mode_after, self.hash_after),
        ):
            if present:
                if mode not in (0o644, 0o755) or not digest:
                    raise DomainError(ErrorCode.INVALID_INPUT, "Incomplete file binding")
                ContentHash(digest, "file-bytes-v1")
            elif mode is not None or digest is not None:
                raise DomainError(ErrorCode.INVALID_INPUT, "Invalid absent-file binding")
        if self.operation == "modify" and self.mode_before != self.mode_after:
            raise DomainError(ErrorCode.INVALID_INPUT, "Mode changes are not supported yet")
        if has_after:
            try:
                content = base64.b64decode(self.content_after_base64, validate=True)
            except (ValueError, TypeError) as exc:
                raise DomainError(ErrorCode.INVALID_INPUT, "Invalid encoded patch content") from exc
            if hashlib.sha256(content).hexdigest() != self.hash_after:
                raise DomainError(ErrorCode.INVALID_INPUT, "Patch content binding mismatch")
        elif self.content_after_base64 is not None:
            raise DomainError(ErrorCode.INVALID_INPUT, "Delete operation contains content")


@dataclass(frozen=True)
class CanonicalProposal:
    base: ProposalBase
    entries: tuple[ChangeEntry, ...]
    generator_provenance: str

    def __post_init__(self) -> None:
        self.base.require()
        if (
            type(self.entries) is not tuple
            or not 1 <= len(self.entries) <= 100
            or len({entry.path for entry in self.entries}) != len(self.entries)
            or not self.generator_provenance
        ):
            raise DomainError(ErrorCode.INVALID_INPUT, "Invalid canonical proposal")

    def payload(self) -> dict:
        return {
            "base": asdict(self.base),
            "entries": [asdict(entry) for entry in self.entries],
            "generator_provenance": self.generator_provenance,
            "patch_artifact_schema_version": "regular-file-proposal-v1",
        }

    @property
    def digest(self) -> str:
        return canonical_hash(self.payload(), "regular-file-proposal-v1").digest


def target_path(value: str) -> bytes:
    if type(value) is not str or len(value) > 1024 or "\\" in value or ":" in value:
        raise DomainError(ErrorCode.INVALID_INPUT, "Unsupported target path")
    raw = value.encode("utf-8", "strict")
    encode_path(raw)
    if any(part.casefold() == ".git" for part in value.split("/")):
        raise DomainError(
            ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Git administrative targets are forbidden"
        )
    return raw


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def parse_candidate(data: bytes) -> dict:
    if len(data) > 1024 * 1024:
        raise DomainError(ErrorCode.INVALID_INPUT, "Candidate size limit exceeded")
    try:

        def reject_constant(value):
            raise ValueError("Non-finite JSON value")

        value = json.loads(data, object_pairs_hook=_object_pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DomainError(ErrorCode.INVALID_INPUT, "Invalid structured candidate") from exc
    if type(value) is not dict or value.keys() != {"operations"}:
        raise DomainError(ErrorCode.INVALID_INPUT, "Candidate may only contain operations")
    if type(value["operations"]) is not list or not 1 <= len(value["operations"]) <= 100:
        raise DomainError(ErrorCode.INVALID_INPUT, "Candidate requires 1 to 100 operations")
    return value


def canonicalize_candidate(
    data: bytes,
    base: ProposalBase,
    baseline: dict[bytes, BaselineFile],
    *,
    generator_provenance: str,
) -> CanonicalProposal:
    base.require()
    if not generator_provenance or len(generator_provenance) > 200:
        raise DomainError(ErrorCode.INVALID_INPUT, "Trusted generator provenance is required")
    candidate = parse_candidate(data)
    entries, touched, collisions = [], set(), {}
    for path in baseline:
        encode_path(path)
        key = unicodedata.normalize("NFC", path.decode("utf-8", "strict")).casefold()
        if key in collisions and collisions[key] != path:
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Baseline has alias collisions")
        collisions[key] = path
    for operation in candidate["operations"]:
        if type(operation) is not dict or not {"path", "operation"} <= operation.keys():
            raise DomainError(ErrorCode.INVALID_INPUT, "Invalid file operation")
        kind = operation["operation"]
        expected = {"path", "operation"} if kind == "delete" else {"path", "operation", "content"}
        if kind not in ("create", "modify", "delete") or operation.keys() != expected:
            raise DomainError(ErrorCode.INVALID_INPUT, "Unsupported operation or authority field")
        path = target_path(operation["path"])
        collision = unicodedata.normalize("NFC", operation["path"]).casefold()
        if path in touched or (collision in collisions and collisions[collision] != path):
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Duplicate or alias target")
        touched.add(path)
        collisions[collision] = path
        before = baseline.get(path)
        if (kind == "create" and before is not None) or (kind != "create" and before is None):
            raise DomainError(
                ErrorCode.INVALID_INPUT, "Operation does not match baseline file state"
            )
        content = None
        if kind != "delete":
            if type(operation["content"]) is not str:
                raise DomainError(
                    ErrorCode.INVALID_INPUT, "Only UTF-8 text candidates are supported"
                )
            content = operation["content"].encode("utf-8", "strict")
            if len(content) > 256 * 1024 or b"\0" in content:
                raise DomainError(ErrorCode.INVALID_INPUT, "Unsupported candidate content")
        if (
            any(sensitive_path(part) for part in operation["path"].split("/"))
            or (before and sensitive_content(before.content))
            or (content is not None and sensitive_content(content))
        ):
            raise DomainError(
                ErrorCode.PROTECTED_STORAGE_UNAVAILABLE,
                "Sensitive changes require an explicit protected policy path",
            )
        if before and content == before.content:
            raise DomainError(ErrorCode.INVALID_INPUT, "No-op changes are not patch operations")
        entries.append(
            ChangeEntry(
                encode_path(path),
                kind,
                before.mode if before else None,
                (before.mode if before else 0o644) if content is not None else None,
                before.digest if before else None,
                hashlib.sha256(content).hexdigest() if content is not None else None,
                base64.b64encode(content).decode("ascii") if content is not None else None,
            )
        )
    # All paths are file targets, so a file cannot also become a parent directory.
    all_paths = set(baseline) | touched
    for path in all_paths:
        parts = path.split(b"/")
        if any(b"/".join(parts[:n]) in all_paths for n in range(1, len(parts))):
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED, "File/directory target conflict")
    return CanonicalProposal(
        base, tuple(sorted(entries, key=lambda entry: entry.path)), generator_provenance
    )


def require_same_base(proposal: CanonicalProposal, current: ProposalBase) -> None:
    current.require()
    if proposal.base != current:
        raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "PROPOSAL_BASE_STALE")


def simulate(
    proposal: CanonicalProposal, baseline: dict[bytes, BaselineFile]
) -> dict[bytes, BaselineFile]:
    """Pure preview only. This function never grants filesystem write authority."""
    result = dict(baseline)
    for entry in proposal.entries:
        path = decode_path(entry.path)
        before = baseline.get(path)
        if (before.digest if before else None) != entry.hash_before or (
            before.mode if before else None
        ) != entry.mode_before:
            raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "TARGET_PREIMAGE_MISMATCH")
        if entry.operation == "delete":
            del result[path]
        else:
            content = base64.b64decode(entry.content_after_base64, validate=True)
            if hashlib.sha256(content).hexdigest() != entry.hash_after:
                raise DomainError(ErrorCode.INVALID_INPUT, "Patch content binding mismatch")
            result[path] = BaselineFile(content, entry.mode_after)
    return result


def actual_change_set(before: dict[bytes, BaselineFile], after: dict[bytes, BaselineFile]) -> dict:
    entries = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        entries.append(
            {
                "path": encode_path(path),
                "operation": "create" if old is None else "delete" if new is None else "modify",
                "hash_before": old.digest if old else None,
                "hash_after": new.digest if new else None,
                "mode_before": old.mode if old else None,
                "mode_after": new.mode if new else None,
            }
        )
    return {
        "entries": entries,
        "schema_version": "regular-change-set-v1",
        "final_diff_hash": canonical_hash(entries, "regular-change-set-v1").digest,
    }


def require_manifest_match(proposal: CanonicalProposal, actual: dict) -> None:
    expected = [
        {key: value for key, value in asdict(entry).items() if key != "content_after_base64"}
        for entry in proposal.entries
    ]

    def normalize(entries):
        return sorted(entries, key=lambda entry: entry["path"])

    if (
        normalize(expected) != normalize(actual["entries"])
        or actual["final_diff_hash"]
        != canonical_hash(actual["entries"], "regular-change-set-v1").digest
    ):
        raise DomainError(ErrorCode.INVALID_INPUT, "CANONICAL_CHANGE_SET_MISMATCH")
