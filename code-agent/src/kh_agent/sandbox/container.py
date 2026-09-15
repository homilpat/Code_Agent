"""Rootless container execution of registered verification commands (M06, Linux runtime).

A plan runs only after the runtime is attested as rootless with cgroup v2 cpu/memory/pids limits
and seccomp. The container sees a runtime-safe source view materialized from a scanner snapshot
(sensitive files and Git metadata are already excluded), read-only, with no network, no host
environment, a non-root user, bounded output and a wall-clock limit; it is always removed.
"""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from kh_agent.core.canonical import canonical_hash
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.repository.snapshot import SourceSnapshot
from kh_agent.sandbox.policy import (
    TRUSTED_PYTEST_INI,
    CompiledCommand,
    SandboxProfile,
    container_plan,
)

RUNTIME_PATH = "/usr/local/bin:/usr/bin:/bin"
MANAGED_LABEL = "knowledge-hub.managed=true"
REQUIRED_CONTROLLERS = frozenset({"cpu", "memory", "pids"})
# pytest exit codes: 0 passed, 1 tests failed, 5 no tests collected; others are runner errors.
PYTEST_STATUS = {0: "PASS", 1: "FAIL", 5: "INCONCLUSIVE"}


@dataclass(frozen=True)
class RuntimeAttestation:
    runtime: str
    executable: str
    capabilities: dict
    digest: str


@dataclass(frozen=True)
class SandboxResult:
    status: str
    exit_code: int | None
    termination_reason: str
    output: str
    output_truncated: bool
    output_sha256: str
    wall_seconds: float
    plan_hash: str
    attestation_digest: str


def runtime_environment() -> dict[str, str]:
    """What the rootless runtime itself needs; nothing reaches the container through it."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return {
        "PATH": RUNTIME_PATH,
        "HOME": str(Path.home()),
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}"),
        "LC_ALL": "C",
    }


def attestation_from_info(executable: str, info: dict) -> RuntimeAttestation:
    """Architecture 28.1 capability descriptor from `podman info` JSON, or refusal."""
    host = info.get("host") or {}
    security = host.get("security") or {}
    missing = []
    if security.get("rootless") is not True:
        missing.append("ROOTLESS")
    if host.get("cgroupVersion") != "v2":
        missing.append("CGROUP_V2")
    if not REQUIRED_CONTROLLERS <= set(host.get("cgroupControllers") or []):
        missing.append("CGROUP_CONTROLLERS")
    if security.get("seccompEnabled") is not True:
        missing.append("SECCOMP")
    if missing:
        raise DomainError(
            ErrorCode.CAPABILITY_NOT_AVAILABLE, "Container runtime lacks " + ", ".join(missing)
        )
    apparmor = security.get("apparmorEnabled") is True
    capabilities = {
        "runtime": "podman",
        "runtime_version": (info.get("version") or {}).get("Version"),
        "oci_runtime": (host.get("ociRuntime") or {}).get("name"),
        "identity_isolation": "ROOTLESS_USER_NAMESPACE",
        "process_isolation": "PRIVATE_PID_IPC_NAMESPACES",
        "network_mode": "NONE",
        "filesystem_read_scope": "RUNTIME_SAFE_SOURCE_VIEW_READ_ONLY",
        "filesystem_write_scope": "BOUNDED_TMPFS_ONLY",
        "secret_inheritance": "NONE",
        "cpu_limit": True,
        "memory_limit": True,
        "process_limit": True,
        "wall_time_limit": True,
        "disk_limit": "TMPFS_SIZE",
        # Podman 4.9 tmpfs mounts cannot cap inode counts, so file-count quota is not enforced.
        "inode_limit": False,
        # OOMKilled is not reported rootless; an uncommanded exit 137 is treated as memory limit.
        "oom_kill_reporting": "EXIT_CODE_137_INFERENCE",
        "syscall_or_runtime_restrictions": "SECCOMP_DEFAULT_PROFILE",
        # AppArmor/SELinux are recorded, not assumed; WSL kernels ship without them.
        "lsm": "APPARMOR" if apparmor else "SELINUX" if security.get("selinuxEnabled") else "NONE",
        "descendant_process_cleanup": "CONTAINER_KILL_AND_REMOVE",
        "artifact_export_policy": "BOUNDED_COMBINED_OUTPUT_ONLY",
    }
    return RuntimeAttestation(
        "podman",
        executable,
        capabilities,
        canonical_hash(capabilities, "sandbox-capability-v1").digest,
    )


def attest(executable: str | None = None) -> RuntimeAttestation:
    if sys.platform != "linux":
        raise DomainError(ErrorCode.UNSUPPORTED_PLATFORM, "Sandbox execution requires Linux")
    path = executable or shutil.which("podman", path=RUNTIME_PATH)
    if not path or not os.path.isabs(path):
        raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "No rootless container runtime")
    try:
        done = subprocess.run(  # noqa: S603 - absolute runtime executable, fixed argv
            [path, "info", "--format", "json"],
            env=runtime_environment(),
            capture_output=True,
            timeout=60,
            check=False,
        )
        info = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "Runtime is not responding") from exc
    if not isinstance(info, dict):
        raise DomainError(ErrorCode.CAPABILITY_NOT_AVAILABLE, "Runtime is not responding")
    return attestation_from_info(path, info)


def materialize_source_view(snapshot: SourceSnapshot, root: Path) -> Path:
    """Write the snapshot into a fresh tree readable by the mapped container user."""
    view = root / "src"
    view.mkdir(mode=0o755)
    view.chmod(0o755)
    for source in snapshot.files:
        relative = os.fsdecode(source.path)
        parts = relative.split("/")
        if relative.startswith("/") or any(part in ("", ".", "..") for part in parts):
            raise DomainError(ErrorCode.INVALID_INPUT, "Unsafe source view path")
        directory = view
        for part in parts[:-1]:
            directory = directory / part
            if not directory.is_dir():
                directory.mkdir(mode=0o755)
                directory.chmod(0o755)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(directory / parts[-1], flags, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(source.content)
        os.chmod(directory / parts[-1], 0o644)
    return view


class RootlessContainerBackend:
    """Architecture 7/28 SandboxBackend for registered commands on an attested rootless runtime."""

    def __init__(
        self,
        image: str,
        profile: SandboxProfile | None = None,
        attestation: RuntimeAttestation | None = None,
    ) -> None:
        self.attestation = attestation or attest()
        self.image = image
        self.profile = profile or SandboxProfile()

    def _runtime(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - attested runtime executable, fixed argv
            [self.attestation.executable, *args],
            env=runtime_environment(),
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def sweep_orphans(self) -> int:
        """Remove managed containers left behind by a crashed run."""
        listed = self._runtime(
            "ps", "--all", "--filter", f"label={MANAGED_LABEL}", "--format", "{{.Names}}"
        )
        names = [name for name in listed.stdout.decode().split() if name.startswith("kh-")]
        for name in names:
            self._runtime("rm", "--force", "--time", "0", name)
        return len(names)

    def execute(self, command: CompiledCommand, snapshot: SourceSnapshot) -> SandboxResult:
        name = "kh-" + secrets.token_hex(8)
        with tempfile.TemporaryDirectory(prefix="kh-sandbox-") as private:
            root = Path(private)
            view = materialize_source_view(snapshot, root)
            config = root / "pytest.ini"
            config.write_text(TRUSTED_PYTEST_INI, encoding="utf-8")
            config.chmod(0o644)
            plan = container_plan(
                command,
                runtime=self.attestation.runtime,
                image=self.image,
                source_view=str(view),
                trusted_config=str(config),
                container_name=name,
                profile=self.profile,
                apparmor_profile=None,
            )
            try:
                return self._run(plan, name, command.timeout_seconds)
            finally:
                self._runtime("rm", "--force", "--time", "0", name)

    def _run(self, plan: dict, name: str, timeout: int) -> SandboxResult:
        limit = self.profile.max_output_bytes
        buffer = bytearray()
        digest = hashlib.sha256()
        exceeded = threading.Event()
        started = time.monotonic()
        process = subprocess.Popen(  # noqa: S603 - attested runtime executable, validated plan
            [self.attestation.executable, *plan["argv"][1:]],
            env=runtime_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        def drain() -> None:
            stream = process.stdout
            if stream is None:
                return
            while chunk := stream.read(65536):
                if exceeded.is_set():
                    continue  # keep draining so the runtime can exit
                room = limit - len(buffer)
                if len(chunk) > room:
                    buffer.extend(chunk[:room])
                    digest.update(chunk[:room])
                    exceeded.set()
                    self._runtime("kill", name)
                else:
                    buffer.extend(chunk)
                    digest.update(chunk)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        reason = "EXITED"
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            reason = "TIMEOUT"
            self._runtime("kill", name)
            process.wait(timeout=60)
        reader.join(timeout=60)
        if exceeded.is_set():
            reason = "OUTPUT_LIMIT"
        exit_code = process.returncode
        inspected = self._runtime("inspect", "--format", "{{.State.OOMKilled}}", name)
        if reason == "EXITED" and inspected.stdout.strip() == b"true":
            reason = "MEMORY_LIMIT"
        elif reason == "EXITED" and exit_code == 137:
            # Rootless Podman reports OOMKilled=false; a SIGKILL this backend did not send can
            # only come from the memory limit inside this sandbox.
            reason = "MEMORY_LIMIT_SUSPECTED"
        if reason == "EXITED":
            status = PYTEST_STATUS.get(exit_code, "ERROR")
        elif reason in ("MEMORY_LIMIT", "MEMORY_LIMIT_SUSPECTED"):
            status = "FAIL"
        else:
            status = "INCONCLUSIVE"  # a timeout or truncated output never proves a result
        return SandboxResult(
            status=status,
            exit_code=exit_code,
            termination_reason=reason,
            output=bytes(buffer).decode("utf-8", "replace"),
            output_truncated=exceeded.is_set(),
            output_sha256=digest.hexdigest(),
            wall_seconds=round(time.monotonic() - started, 3),
            plan_hash=plan["plan_hash"],
            attestation_digest=self.attestation.digest,
        )
