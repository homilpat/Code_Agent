"""Read-only preview of one text replacement from a bounded source snapshot.

This is not a canonical proposal or authority to apply a patch. Source snapshots
remain PARTIAL, so preview evidence cannot be promoted into verification.
"""

import difflib
import hashlib

from kh_agent.core.canonical import canonical_hash
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.patch.canonical import parse_candidate, target_path
from kh_agent.repository.snapshot import SourceFile, SourceSnapshot
from kh_agent.security.ingestion import sensitive_content

MAX_DIFF_BYTES = 1024 * 1024


def preview_candidate(data: bytes, snapshot: SourceSnapshot) -> dict:
    candidate = parse_candidate(data)
    if len(candidate["operations"]) != 1:
        raise DomainError(ErrorCode.INVALID_INPUT, "Preview accepts one file modification")
    operation = candidate["operations"][0]
    if (
        type(operation) is not dict
        or operation.keys() != {"path", "operation", "content"}
        or operation["operation"] != "modify"
        or type(operation["content"]) is not str
    ):
        raise DomainError(ErrorCode.INVALID_INPUT, "Preview requires one text modification")
    path = target_path(operation["path"])
    if not path.endswith(b".py"):
        raise DomainError(ErrorCode.INVALID_INPUT, "Preview currently supports Python files")
    files = {source.path: source for source in snapshot.files}
    source = files.get(path)
    if source is None:
        raise DomainError(ErrorCode.INVALID_INPUT, "Target is not in the safe source view")
    after = operation["content"].encode("utf-8")
    if len(after) > 256 * 1024 or b"\0" in after or sensitive_content(after):
        raise DomainError(ErrorCode.PROTECTED_STORAGE_UNAVAILABLE, "Unsafe preview content")
    if after == source.content:
        raise DomainError(ErrorCode.INVALID_INPUT, "No change to preview")
    try:
        before_text = source.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DomainError(ErrorCode.INVALID_INPUT, "Target is not UTF-8 text") from exc
    diff = "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            operation["content"].splitlines(keepends=True),
            fromfile=f"a/{operation['path']}",
            tofile=f"b/{operation['path']}",
        )
    )
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise DomainError(ErrorCode.INVALID_INPUT, "Preview output exceeds limit")
    return {
        "status": "PREVIEW_ONLY",
        "path": operation["path"],
        "before_sha256": source.content_hash,
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "candidate_hash": canonical_hash(candidate, "preview-candidate-v1").digest,
        "source_snapshot_hash": snapshot.snapshot_hash,
        "source_completeness": snapshot.completeness,
        "diff": diff,
    }


def candidate_source_view(data: bytes, snapshot: SourceSnapshot) -> SourceSnapshot:
    """Build an in-memory test view after the same bounded preview validation."""
    preview = preview_candidate(data, snapshot)
    candidate = parse_candidate(data)
    path = target_path(preview["path"])
    content = candidate["operations"][0]["content"].encode("utf-8")
    files = tuple(
        SourceFile(path, content, preview["after_sha256"]) if source.path == path else source
        for source in snapshot.files
    )
    view_hash = canonical_hash(
        {
            "base": snapshot.snapshot_hash,
            "candidate": preview["candidate_hash"],
            "files": [[source.path.hex(), source.content_hash] for source in files],
        },
        "candidate-test-view-v1",
    ).digest
    return SourceSnapshot(
        files,
        view_hash,
        snapshot.policy_version,
        snapshot.exclusions,
        "PARTIAL",
        (*snapshot.limitations, "EXPERIMENTAL_CANDIDATE_VIEW"),
    )
