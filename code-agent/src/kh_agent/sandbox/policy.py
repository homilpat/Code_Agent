import re
from dataclasses import asdict, dataclass

from kh_agent.core.canonical import canonical_hash
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.patch.canonical import target_path

# Mounted read-only at /trusted/pytest.ini. `-c` makes repository ini files irrelevant and
# --rootdir keeps discovery inside the source view; pythonpath covers flat and src layouts.
TRUSTED_PYTEST_INI = (
    "[pytest]\n"
    "addopts =\n"
    "pythonpath = /workspace/src /workspace/src/src\n"
    "cache_dir = /tmp/pytest-cache\n"
)
IMAGE_REFERENCE = re.compile(r"(?:[a-z0-9][a-z0-9./:_-]*@)?sha256:[0-9a-f]{64}|[0-9a-f]{64}")
RUNTIME_SYNTAX = {
    "docker": {
        "readonly": "readonly",
        "no_new_privileges": "no-new-privileges=true",
        "tmp_inodes": ",nr_inodes=16384",
        "out_inodes": ",nr_inodes=65536",
    },
    # Podman 4.9 rejects nr_inodes on tmpfs; only the byte size is capped there, and the
    # attested capability descriptor records that no inode limit is enforced.
    "podman": {
        "readonly": "ro=true",
        "no_new_privileges": "no-new-privileges",
        "tmp_inodes": "",
        "out_inodes": "",
    },
}


@dataclass(frozen=True)
class PytestRequest:
    targets: tuple[str, ...]
    timeout_seconds: int = 120


@dataclass(frozen=True)
class CompiledCommand:
    template_id: str
    template_version: str
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    timeout_seconds: int
    requires_sandbox: bool = True

    @property
    def fingerprint(self) -> str:
        return canonical_hash(
            {
                **asdict(self),
                "argv": list(self.argv),
                "environment": [list(item) for item in self.environment],
            },
            "command-v1",
        ).digest


def compile_pytest(request: PytestRequest) -> CompiledCommand:
    if (
        type(request.targets) is not tuple
        or not 1 <= len(request.targets) <= 100
        or type(request.timeout_seconds) is not int
        or not 1 <= request.timeout_seconds <= 600
    ):
        raise DomainError(ErrorCode.INVALID_INPUT, "Invalid pytest request bounds")
    if len(set(request.targets)) != len(request.targets):
        raise DomainError(ErrorCode.INVALID_INPUT, "Duplicate test target")
    for target in request.targets:
        target_path(target)
        if target.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./-]+", target):
            raise DomainError(ErrorCode.INVALID_INPUT, "Unsupported test path")
    return CompiledCommand(
        "python-pytest",
        "python-pytest-v2",
        (
            "/usr/local/bin/python",
            # -I ignores PYTHON* variables, user site and the working directory; -B is explicit
            # because -I also ignores PYTHONDONTWRITEBYTECODE.
            "-I",
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            "/trusted/pytest.ini",
            "--rootdir=/workspace/src",
            "--override-ini",
            "addopts=",
            "--",
            *request.targets,
        ),
        (
            ("PATH", "/usr/local/bin:/usr/bin:/bin"),
            ("HOME", "/tmp/home"),  # noqa: S108 - path inside the sandbox container
            ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1"),
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("TMPDIR", "/tmp"),  # noqa: S108 - path inside the sandbox container
        ),
        request.timeout_seconds,
    )


@dataclass(frozen=True)
class SandboxProfile:
    version: str = "verification-default-v1"
    memory_mib: int = 2048
    cpus: int = 2
    pids: int = 256
    output_mib: int = 1024
    tmp_mib: int = 512
    max_output_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for value, ceiling in (
            (self.memory_mib, 8192),
            (self.cpus, 8),
            (self.pids, 512),
            (self.output_mib, 2048),
            (self.tmp_mib, 1024),
            (self.max_output_bytes, 4 * 1024 * 1024),
        ):
            if type(value) is not int or not 0 < value <= ceiling:
                raise DomainError(ErrorCode.INVALID_INPUT, "Invalid sandbox resource ceiling")


def container_plan(
    command: CompiledCommand,
    *,
    runtime: str,
    image: str,
    source_view: str,
    trusted_config: str,
    container_name: str,
    profile: SandboxProfile | None = None,
    apparmor_profile: str | None = None,
) -> dict:
    """Produce a reviewable plan only; flags alone do not attest a safe runtime.

    `sandbox.container` executes a plan only after attesting rootless isolation, cgroup limits
    and seccomp. The AppArmor option is added only when the attested runtime supports it.
    """
    profile = profile or SandboxProfile()
    if runtime not in RUNTIME_SYNTAX:
        raise DomainError(ErrorCode.INVALID_INPUT, "Unsupported container runtime")
    syntax = RUNTIME_SYNTAX[runtime]
    try:
        marker = command.argv.index("--")
        registered = compile_pytest(
            PytestRequest(command.argv[marker + 1 :], command.timeout_seconds)
        )
    except (ValueError, AttributeError, TypeError) as exc:
        raise DomainError(ErrorCode.INVALID_INPUT, "Command is not a registered template") from exc
    if command != registered:
        raise DomainError(
            ErrorCode.INVALID_INPUT, "Compiled command was modified after policy validation"
        )
    if not IMAGE_REFERENCE.fullmatch(image):
        raise DomainError(ErrorCode.INVALID_INPUT, "An immutable local image digest is required")
    if not re.fullmatch(r"kh-[a-z0-9-]{1,60}", container_name):
        raise DomainError(ErrorCode.INVALID_INPUT, "Invalid owned container name")
    if apparmor_profile is not None and not re.fullmatch(r"[a-z0-9-]{1,64}", apparmor_profile):
        raise DomainError(ErrorCode.INVALID_INPUT, "Invalid AppArmor profile name")
    for path in (source_view, trusted_config):
        if (
            not path.startswith("/")
            or any(c in path for c in (",", "\n", "\r", "\0"))
            or ".." in path.split("/")
            or path == "/"
        ):
            raise DomainError(ErrorCode.INVALID_INPUT, "Unsafe mount path")
    if not command.requires_sandbox:
        raise DomainError(
            ErrorCode.INVALID_INPUT, "Project code cannot use a host execution profile"
        )
    argv = [
        runtime,
        "run",
        "--pull=never",
        "--name",
        container_name,
        "--label",
        "knowledge-hub.managed=true",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        f"--security-opt={syntax['no_new_privileges']}",
    ]
    if apparmor_profile is not None:
        argv.append(f"--security-opt=apparmor={apparmor_profile}")
    argv += [
        "--user=65532:65532",
        f"--pids-limit={profile.pids}",
        f"--memory={profile.memory_mib}m",
        f"--memory-swap={profile.memory_mib}m",
        f"--cpus={profile.cpus}",
        "--ipc=private",
        "--workdir=/workspace/src",
        "--tmpfs",
        # Container-private tmpfs mount, not a host temporary path.
        f"/tmp:rw,noexec,nosuid,nodev,size={profile.tmp_mib}m{syntax['tmp_inodes']}",  # noqa: S108
        "--tmpfs",
        f"/workspace/out:rw,nosuid,nodev,size={profile.output_mib}m{syntax['out_inodes']}",
        "--mount",
        f"type=bind,src={source_view},dst=/workspace/src,{syntax['readonly']}",
        "--mount",
        f"type=bind,src={trusted_config},dst=/trusted/pytest.ini,{syntax['readonly']}",
    ]
    for name, value in command.environment:
        argv.extend(("--env", f"{name}={value}"))
    # Override the image entrypoint; no image-controlled wrapper may alter the command.
    argv.extend(("--entrypoint", command.argv[0], image, *command.argv[1:]))
    value = {
        "argv": argv,
        "runtime": runtime,
        "lsm_profile": apparmor_profile,
        "profile": asdict(profile),
        "command_hash": command.fingerprint,
        "timeout_seconds": command.timeout_seconds,
        "requires_runtime_attestation": True,
        "execution_available": False,
    }
    return {**value, "plan_hash": canonical_hash(value, "sandbox-plan-v1").digest}
