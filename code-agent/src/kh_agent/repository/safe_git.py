"""Safe Git inspection that produces mutation-safety target snapshots (inspection only).

Only fixed plumbing commands run, with an environment built from scratch and trusted config
overrides, so repository hooks, fsmonitor, external diff/textconv, credential helpers, pagers and
clean/smudge/process filters never execute and no network transport is allowed. Worktree state is
synthesized from HEAD/index plumbing plus descriptor-relative reads instead of `git status`; a
path whose exact comparison would need Git conversion is reported as uncertain, never as clean.
"""

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from kh_agent.core.canonical import canonical_hash, encode_path
from kh_agent.core.clock import utc_now
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.repository.identity import RepositoryIdentity
from kh_agent.repository.metadata import MetadataInspector
from kh_agent.security.ingestion import IngestionPolicy, sensitive_path
from kh_agent.security.linux_fs import open_no_alias

SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
CHANGE_SET_SCHEMA = "git-change-set-v1"
CLEAN = f"CLEAN:{CHANGE_SET_SCHEMA}"
OUTPUT_LIMIT = 32 * 1024 * 1024
# Passed as `-c` on every invocation; command-line config overrides repository config.
CONFIG_OVERRIDES = (
    "core.hooksPath=/dev/null",
    "core.fsmonitor=false",
    "core.untrackedCache=false",
    "core.pager=cat",
    "core.attributesFile=/dev/null",
    "credential.helper=",
    "diff.external=",
    "protocol.allow=never",
    "submodule.recurse=false",
    "gc.auto=0",
    "maintenance.auto=false",
)
# Attributes that make Git transform content before comparing it with the index.
ALWAYS_UNCERTAIN = frozenset({"filter", "ident", "working-tree-encoding"})
CONVERSION_ATTRIBUTES = (*sorted(ALWAYS_UNCERTAIN), "text", "eol")
TRACKED_CONFIG = (
    r"^(extensions\.partialclone|remote\..*\.promisor|core\.sparsecheckout|core\.autocrlf"
    r"|core\.eol|core\.filemode)$"
)
TRUE = frozenset({"true", "yes", "on", "1"})


def git_environment(home: str) -> dict[str, str]:
    """A complete environment: nothing, including GIT_DIR or alternates, is inherited."""
    return {
        "PATH": SAFE_PATH,
        "HOME": home,
        "XDG_CONFIG_HOME": home,
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
        "SSH_ASKPASS": "/bin/false",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "GIT_EDITOR": "true",
        "GIT_SEQUENCE_EDITOR": "true",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
    }


@dataclass(frozen=True)
class IndexEntry:
    mode: str
    oid: str
    stage: int
    path: bytes


@dataclass(frozen=True)
class TargetSnapshot:
    """Architecture 24.2 TargetSnapshot for a Git worktree; evidence holds no source bodies."""

    target_id: str
    target_type: str
    target_version: str | None
    state_digest: str
    scope: str
    captured_at_utc: str
    capture_method: str
    completeness: str
    mutation_ready: bool
    evidence: dict


def change_digest(records: object) -> str:
    return canonical_hash(records, CHANGE_SET_SCHEMA).digest


class SafeGitInspector:
    def __init__(
        self,
        identity: RepositoryIdentity,
        repository_id: str,
        policy: IngestionPolicy | None = None,
        *,
        git: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        if sys.platform != "linux":
            raise DomainError(ErrorCode.UNSUPPORTED_PLATFORM, "Safe Git inspection requires Linux")
        executable = git or shutil.which("git", path=SAFE_PATH)
        if not executable or not os.path.isabs(executable):
            raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "No trusted git executable")
        self.identity = identity
        self.repository_id = repository_id
        self.policy = policy or IngestionPolicy()
        self.git = executable
        self.timeout = timeout

    def _git(self, *args: str, stdin: bytes = b"", allowed: tuple[int, ...] = (0,)) -> tuple:
        argv = [
            self.git,
            "--no-optional-locks",
            f"--git-dir={self.identity.git_dir}",
            f"--work-tree={self.identity.canonical_root}",
        ]
        for override in CONFIG_OVERRIDES:
            argv += ["-c", override]
        argv += args
        with tempfile.TemporaryDirectory(prefix="kh-safe-git-") as home:
            try:
                done = subprocess.run(  # noqa: S603 - absolute git, fixed plumbing argv
                    argv,
                    cwd=self.identity.canonical_root,
                    env=git_environment(home),
                    input=stdin,
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise DomainError(
                    ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Git inspection timed out"
                ) from exc
        if done.returncode not in allowed or len(done.stdout) > OUTPUT_LIMIT:
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Git inspection failed")
        return done.returncode, done.stdout

    def _head(self) -> dict:
        code, out = self._git("symbolic-ref", "-q", "HEAD", allowed=(0, 1))
        ref = out.strip() if code == 0 else None
        if ref is not None and not ref.startswith(b"refs/heads/"):
            return {"head_state": "UNRESOLVED", "branch": None, "commit_sha": None}
        branch = os.fsdecode(ref[len(b"refs/heads/") :]) if ref is not None else None
        code, out = self._git("rev-parse", "--verify", "-q", "HEAD^{commit}", allowed=(0, 1, 128))
        if code == 0:
            state = "NORMAL" if ref is not None else "DETACHED"
            return {
                "head_state": state,
                "branch": branch,
                "commit_sha": out.strip().decode("ascii"),
            }
        # UNBORN only when HEAD names a branch and the repository has no refs at all yet.
        _, refs = self._git("for-each-ref", "--count=1", "--format=%(refname)")
        state = "UNBORN" if ref is not None and not refs.strip() else "UNRESOLVED"
        return {"head_state": state, "branch": branch, "commit_sha": None}

    def _config(self) -> dict[str, str]:
        _, raw = self._git(
            "config", "--local", "-z", "--get-regexp", TRACKED_CONFIG, allowed=(0, 1)
        )
        config = {}
        for item in raw.split(b"\0"):
            if item:
                key, _, value = item.partition(b"\n")
                config[key.decode("utf-8", "replace").lower()] = value.decode("utf-8", "replace")
        return config

    def _object_state(self, config: dict[str, str], skip_worktree: int) -> dict:
        alternates = Path(self.identity.common_dir) / "objects" / "info" / "alternates"
        alternates_present = alternates.exists() or alternates.is_symlink()
        _, replace = self._git("for-each-ref", "--format=%(refname)", "refs/replace/")
        promisor = "extensions.partialclone" in config or any(
            key.startswith("remote.") and key.endswith(".promisor") and value.lower() in TRUE
            for key, value in config.items()
        )
        return {
            "alternates_present": alternates_present,
            # No trusted shared-store registry exists yet, so any alternates are unauthorized.
            "object_source_authorization": "UNKNOWN" if alternates_present else "LOCAL_REPOSITORY",
            "replace_ref_count": sum(1 for line in replace.splitlines() if line),
            "partial_clone_enabled": promisor,
            "sparse_checkout_enabled": config.get("core.sparsecheckout", "").lower() in TRUE,
            "skip_worktree_count": skip_worktree,
        }

    def _index(self) -> list[IndexEntry]:
        _, raw = self._git("ls-files", "-z", "--stage")
        entries = []
        for record in raw.split(b"\0"):
            if not record:
                continue
            meta, _, path = record.partition(b"\t")
            mode, oid, stage = meta.split(b" ")
            entries.append(IndexEntry(mode.decode("ascii"), oid.decode("ascii"), int(stage), path))
        return entries

    def _skip_worktree(self) -> set[bytes]:
        _, raw = self._git("ls-files", "-z", "-t")
        return {record[2:] for record in raw.split(b"\0") if record[:1] in (b"S", b"s")}

    def _staged(self, commit: str | None) -> list[dict]:
        if commit is None:
            _, empty = self._git("hash-object", "-t", "tree", "--stdin")
            base = empty.strip().decode("ascii")
        else:
            base = commit
        # Tree-to-index comparison never reads worktree content, so no filter can run.
        _, raw = self._git(
            "diff-index",
            "--cached",
            "-z",
            "--raw",
            "--no-abbrev",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            base,
            "--",
        )
        fields = raw.split(b"\0")
        records = []
        for index in range(0, len(fields) - 1, 2):
            if not fields[index].startswith(b":"):
                break
            old_mode, new_mode, old_oid, new_oid, status = fields[index][1:].decode().split(" ")
            records.append(
                {
                    "path": encode_path(fields[index + 1]),
                    "kind": status,
                    "head_mode": old_mode,
                    "head_oid": old_oid,
                    "index_mode": new_mode,
                    "index_oid": new_oid,
                }
            )
        return records

    def _attributes(self, paths: list[bytes]) -> dict[bytes, set[str]]:
        if not paths:
            return {}
        _, raw = self._git(
            "check-attr", "-z", "--stdin", *CONVERSION_ATTRIBUTES, stdin=b"\0".join(paths) + b"\0"
        )
        fields = raw.split(b"\0")
        result: dict[bytes, set[str]] = {}
        for index in range(0, len(fields) - 2, 3):
            path, attribute, value = fields[index : index + 3]
            if value not in (b"unspecified", b"unset"):
                result.setdefault(path, set()).add(attribute.decode("ascii"))
        return result

    def _worktree_object(self, root_fd: int, path: bytes, object_format: str) -> tuple:
        """(kind, mode, git object id) read through openat2 without following any alias."""
        if any(sensitive_path(part) for part in os.fsdecode(path).split("/")):
            return "SENSITIVE", None, None
        parent, _, name = path.rpartition(b"/")
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            parent_fd = open_no_alias(parent, flags, root_fd=root_fd) if parent else os.dup(root_fd)
        except DomainError:
            absolute = os.path.join(os.fsencode(self.identity.canonical_root), path)
            return ("OTHER" if os.path.lexists(absolute) else "MISSING"), None, None
        try:
            info = os.lstat(name, dir_fd=parent_fd)
            digest = hashlib.new(object_format, usedforsecurity=False)
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(name, dir_fd=parent_fd)
                digest.update(b"blob %d\0" % len(target) + target)
                return "SYMLINK", "120000", digest.hexdigest()
            if not stat.S_ISREG(info.st_mode):
                return "OTHER", None, None
            fd = open_no_alias(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, root_fd=root_fd)
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    return "UNREADABLE", None, None
                digest.update(b"blob %d\0" % opened.st_size)
                total = 0
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    digest.update(chunk)
            if total != opened.st_size:
                return "UNREADABLE", None, None
            return "FILE", "100755" if info.st_mode & stat.S_IXUSR else "100644", digest.hexdigest()
        except FileNotFoundError:
            return "MISSING", None, None
        except (OSError, DomainError):
            return "UNREADABLE", None, None
        finally:
            os.close(parent_fd)

    def _unstaged(
        self, entries: list[IndexEntry], skip: set[bytes], object_format: str, config: dict
    ) -> tuple[list[dict], list[bytes]]:
        checked = [e for e in entries if e.stage == 0 and e.mode != "160000" and e.path not in skip]
        attributes = self._attributes([entry.path for entry in checked])
        conversions = config.get("core.autocrlf", "").lower() in TRUE | {"input"} or bool(
            config.get("core.eol")
        )
        filemode = config.get("core.filemode", "true").lower() in TRUE
        records: list[dict] = []
        uncertain: list[bytes] = []
        unmerged = sorted({entry.path for entry in entries if entry.stage != 0})
        records.extend({"path": encode_path(path), "kind": "UNMERGED"} for path in unmerged)
        root = os.fsencode(self.identity.canonical_root)
        root_fd = open_no_alias(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for entry in checked:
                kind, mode, oid = self._worktree_object(root_fd, entry.path, object_format)
                attrs = attributes.get(entry.path, set())
                expected = "SYMLINK" if entry.mode == "120000" else "FILE"

                def record(change: str, entry=entry, mode=mode, oid=oid) -> dict:
                    return {
                        "path": encode_path(entry.path),
                        "kind": change,
                        "index_mode": entry.mode,
                        "index_oid": entry.oid,
                        "worktree_mode": mode,
                        "worktree_oid": oid,
                    }

                if kind in ("SENSITIVE", "UNREADABLE") or attrs & ALWAYS_UNCERTAIN:
                    uncertain.append(entry.path)
                elif kind == "MISSING":
                    records.append(record("DELETED"))
                elif kind != expected:
                    records.append(record("TYPE_CHANGED"))
                elif oid != entry.oid:
                    if attrs or conversions:
                        uncertain.append(entry.path)
                    else:
                        records.append(record("MODIFIED"))
                elif filemode and mode != entry.mode:
                    records.append(record("MODE_CHANGED"))
        finally:
            os.close(root_fd)
        return records, uncertain

    def _untracked(self, object_format: str) -> list[dict]:
        _, raw = self._git("ls-files", "-z", "--others", "--exclude-standard")
        records = []
        root = os.fsencode(self.identity.canonical_root)
        root_fd = open_no_alias(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for path in sorted(item for item in raw.split(b"\0") if item):
                parts = os.fsdecode(path).split("/")
                if (
                    path.endswith(b"/")  # a nested repository boundary, not a source file
                    or any(part in self.policy.excluded_directories for part in parts)
                    or any(sensitive_path(part) for part in parts)
                ):
                    continue
                kind, mode, oid = self._worktree_object(root_fd, path, object_format)
                records.append(
                    {
                        "path": encode_path(path),
                        "kind": "UNTRACKED",
                        "worktree_mode": mode,
                        "worktree_oid": oid if kind in ("FILE", "SYMLINK") else None,
                    }
                )
        finally:
            os.close(root_fd)
        return records

    def snapshot(self) -> TargetSnapshot:
        operations = MetadataInspector().inspect(self.identity)["git_operations"]
        object_format = self._git("rev-parse", "--show-object-format")[1].strip().decode("ascii")
        if object_format not in ("sha1", "sha256"):
            raise DomainError(ErrorCode.SAFE_GIT_POLICY_BLOCKED, "Unsupported object format")
        head = self._head()
        config = self._config()
        skip = self._skip_worktree()
        objects = self._object_state(config, len(skip))
        entries = self._index()
        staged = self._staged(head["commit_sha"])
        unstaged, uncertain = self._unstaged(entries, skip, object_format, config)
        untracked = self._untracked(object_format)
        dirty = bool(staged or unstaged or untracked)
        changes = {
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "comparison_uncertain": [encode_path(path) for path in sorted(uncertain)],
        }
        worktree = {
            **changes,
            "dirty": dirty,
            "staged_diff_hash": change_digest(staged) if staged else CLEAN,
            "unstaged_diff_hash": change_digest(unstaged) if unstaged else CLEAN,
            "working_tree_diff_hash": change_digest(changes) if dirty or uncertain else CLEAN,
        }
        if objects["alternates_present"]:
            completeness = "BLOCKED"
        elif (
            uncertain
            or skip
            or objects["sparse_checkout_enabled"]
            or objects["partial_clone_enabled"]
        ):
            completeness = "PARTIAL"
        else:
            completeness = "COMPLETE"
        mutation_ready = (
            head["head_state"] == "NORMAL"
            and not operations
            and not dirty
            and completeness == "COMPLETE"
            and objects["replace_ref_count"] == 0
        )
        evidence = {
            "schema_version": "target-snapshot-v1",
            "object_format": object_format,
            "head": head,
            "git_operations": operations,
            "object_state": objects,
            "worktree": worktree,
            "ingestion_policy_version": self.policy.version,
        }
        identity = {
            "canonical_root": self.identity.canonical_root,
            "root_identity": self.identity.root_identity,
            "common_identity": self.identity.common_identity,
        }
        return TargetSnapshot(
            target_id=self.repository_id,
            target_type="GIT_WORKTREE",
            target_version=head["commit_sha"],
            state_digest=canonical_hash(
                {"repository": identity, **evidence}, "target-snapshot-v1"
            ).digest,
            scope="REPOSITORY_WORKTREE",
            captured_at_utc=utc_now(),
            capture_method="safe-git-inspection-v1",
            completeness=completeness,
            mutation_ready=mutation_ready,
            evidence=evidence,
        )


def inspect_target(
    identity: RepositoryIdentity, repository_id: str, policy: IngestionPolicy | None = None
) -> TargetSnapshot:
    return SafeGitInspector(identity, repository_id, policy).snapshot()
