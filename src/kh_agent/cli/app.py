import platform
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from kh_agent import __version__
from kh_agent.application import Application
from kh_agent.cli.renderer import render
from kh_agent.cli.runtime import require_linux_store
from kh_agent.core.enums import Permission
from kh_agent.core.errors import DomainError, ErrorCode
from kh_agent.core.ids import CommandRequestId
from kh_agent.identity.service import IdentityService, current_os_principal
from kh_agent.repository.identity import RepositoryIdentityResolver
from kh_agent.repository.safe_git import inspect_target
from kh_agent.repository.snapshot import SourceScanner
from kh_agent.security.policy import load_policy
from kh_agent.store.database import Database
from kh_agent.store.registry import Registry

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    help="Standalone local-first code agent (experimental release).",
)
repo_app = typer.Typer(no_args_is_help=True, help="Explicit local repository registration.")
access_app = typer.Typer(no_args_is_help=True, help="Local store administrator ACL management.")
app.add_typer(repo_app, name="repo")
app.add_typer(access_app, name="access")
LEGACY_STORE = Path.home() / ".knowledge-hub"
DEFAULT_STORE = LEGACY_STORE if LEGACY_STORE.exists() else Path.home() / ".code-agent"


@app.callback()
def options(
    ctx: typer.Context,
    store: Annotated[
        Path, typer.Option(help="Trusted store outside repositories.")
    ] = DEFAULT_STORE,
    no_color: Annotated[bool, typer.Option(help="Output is always plain JSON.")] = False,
) -> None:
    ctx.obj = store


def _run(ctx: typer.Context, operation: Callable[[Database], Any]) -> None:
    db = None
    try:
        root = require_linux_store(ctx.obj)
        legacy_db = root / "db" / "knowledge-hub.db"
        db_path = legacy_db if legacy_db.exists() else root / "db" / "code-agent.db"
        db = Database(db_path)
        typer.echo(render(operation(db)))
    except DomainError as exc:
        typer.echo(render({"error": exc.code.value, "message": exc.message}), err=True)
        raise typer.Exit(
            3 if exc.code in (ErrorCode.ACCESS_DENIED, ErrorCode.IDENTITY_UNRESOLVED) else 2
        ) from None
    except (OSError, ValueError) as exc:
        # No raw exception strings: they can include paths or credential-bearing input.
        typer.echo(render({"error": "INVALID_INPUT_OR_ENVIRONMENT"}), err=True)
        raise typer.Exit(2) from exc
    finally:
        if db:
            db.close()


def _application(ctx: typer.Context, db: Database) -> Application:
    root = Path(ctx.obj).expanduser()
    policy_path = root / "policy" / "security.yaml"
    if not policy_path.exists() and not policy_path.is_symlink():
        return Application(db, target_inspector=inspect_target)
    repositories = tuple(
        Path(row[0]) for row in db.rows("SELECT canonical_root FROM repository_roots")
    )
    policy = load_policy(root, repositories)
    return Application(
        db,
        scanner=SourceScanner(policy.ingestion),
        risk_policy=policy.risk,
        target_inspector=lambda identity, repository_id: inspect_target(
            identity, repository_id, policy.ingestion
        ),
    )


@app.command("policy-check")
def policy_check(ctx: typer.Context) -> None:
    """Validate the fixed policy/security.yaml file in the trusted store."""

    def operation(db):
        IdentityService(db).resolve()
        repositories = tuple(
            Path(row[0]) for row in db.rows("SELECT canonical_root FROM repository_roots")
        )
        policy = load_policy(Path(ctx.obj).expanduser(), repositories)
        return {
            "policy_version": policy.version,
            "policy_hash": policy.content_hash,
            "risk_policy_hash": policy.risk.fingerprint,
        }

    _run(ctx, operation)


@app.command()
def doctor() -> None:
    """Report capabilities without reading repository content or starting processes."""
    typer.echo(
        render(
            {
                "agent_version": __version__,
                "platform": sys.platform,
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "supported_runtime": "WSL2/Linux on local Linux filesystem",
                "stateful_platform_supported": sys.platform == "linux",
                "implemented": [
                    "domain",
                    "sqlite_audit",
                    "local_identity_acl",
                    "repository_registration",
                    "metadata_status",
                    "history",
                    "patch_verification_persistence",
                ],
                "source_analysis": "PYTHON_STATIC_PARTIAL_LINUX_ONLY",
                "sandbox": "REQUIRES_ROOTLESS_PODMAN_AND_PREBUILT_IMAGE",
                "approval_apply": "NOT_AVAILABLE",
                "web_auth_bridge": "NOT_AVAILABLE",
            }
        )
    )


@app.command()
def init(ctx: typer.Context) -> None:
    """Initialize a private local store and explicitly map the current Linux UID."""
    _run(ctx, lambda db: {"user_id": Registry(db).bootstrap(current_os_principal())})


@repo_app.command("register")
def register(ctx: typer.Context, path: Path) -> None:
    """Register physical Git identity and grant the administrator repository permissions."""

    def operation(db):
        actor = IdentityService(db).resolve()
        physical = RepositoryIdentityResolver().resolve(path)
        store_root = Path(ctx.obj).expanduser().resolve()
        if store_root.is_relative_to(Path(physical.canonical_root)):
            raise DomainError(ErrorCode.ACCESS_DENIED, "Trusted store must be outside repository")
        return Registry(db).register(actor, physical, str(CommandRequestId.new()))

    _run(ctx, operation)


@access_app.command("add-user")
def add_user(ctx: typer.Context, uid: Annotated[int, typer.Argument(min=0)]) -> None:
    _run(
        ctx,
        lambda db: {
            "user_id": Registry(db).add_user(IdentityService(db).resolve(), f"linux-uid:{uid}")
        },
    )


def _permission(
    ctx: typer.Context, user_id: str, repository_id: str, permission: Permission, grant: bool
) -> None:
    def operation(db):
        Registry(db).permission(
            IdentityService(db).resolve(), user_id, repository_id, permission, grant=grant
        )
        return {"permission": permission.value, "granted": grant}

    _run(ctx, operation)


@access_app.command("grant")
def grant(ctx: typer.Context, user_id: str, repository_id: str, permission: Permission) -> None:
    _permission(ctx, user_id, repository_id, permission, True)


@access_app.command("revoke")
def revoke(ctx: typer.Context, user_id: str, repository_id: str, permission: Permission) -> None:
    _permission(ctx, user_id, repository_id, permission, False)


RepoOption = Annotated[Path, typer.Option("--repo", help="Repository path, defaults to cwd.")]


@app.command()
def status(ctx: typer.Context, repo: RepoOption = Path(".")) -> None:
    """Read authorized Safe Git HEAD, index and worktree status."""
    _run(ctx, lambda db: _application(ctx, db).execute("status", repo))


@app.command()
def history(ctx: typer.Context, repo: RepoOption = Path(".")) -> None:
    """Read the last 100 metadata audit events after a current ACL check."""
    _run(ctx, lambda db: _application(ctx, db).execute("history", repo))


def _pending(ctx: typer.Context, command: str, repo: Path) -> None:
    _run(ctx, lambda db: _application(ctx, db).execute(command, repo))


@app.command()
def explain(ctx: typer.Context, target: str, repo: RepoOption = Path(".")) -> None:
    """Explain a relative Python file using static definitions, imports and call expressions."""
    _run(ctx, lambda db: _application(ctx, db).execute("explain", repo, target))


@app.command()
def impact(ctx: typer.Context, target: str, repo: RepoOption = Path(".")) -> None:
    """Find import-name candidates for a Python file; risk is not available yet."""
    _run(ctx, lambda db: _application(ctx, db).execute("impact", repo, target))


@app.command()
def semantic(
    ctx: typer.Context,
    target: str,
    line: Annotated[int, typer.Option(min=1, help="One-based source line.")],
    column: Annotated[int, typer.Option(min=1, help="One-based UTF-16 column.")],
    image: Annotated[str, typer.Option(help="Prebuilt immutable pyright image ID.")],
    repo: RepoOption = Path("."),
) -> None:
    """Find definitions, references and diagnostics using sandboxed pyright."""
    _run(ctx, lambda db: _application(ctx, db).semantic_query(repo, target, line, column, image))


@app.command()
def modify(
    ctx: typer.Context,
    request: str,
    repo: RepoOption = Path("."),
    target: Annotated[str | None, typer.Option(help="One Python source path.")] = None,
    model: Annotated[str | None, typer.Option(help="Loaded local model identifier.")] = None,
    port: Annotated[int, typer.Option(min=1, max=65535)] = 1234,
    image: Annotated[str | None, typer.Option(help="Prebuilt immutable Podman image ID.")] = None,
    test: Annotated[list[str] | None, typer.Option(help="Registered pytest path.")] = None,
) -> None:
    """Generate a local candidate; optionally test it in rootless Podman."""
    if (image is None) != (not test):
        raise typer.BadParameter("--image and at least one --test must be supplied together")
    if target is None or model is None:
        _pending(ctx, "modify", repo)
        return
    if image is not None:
        _run(
            ctx,
            lambda db: _application(ctx, db).generate_and_verify(
                repo, target, request, model, image, tuple(test or ()), port
            ),
        )
        return
    _run(ctx, lambda db: _application(ctx, db).generate_preview(repo, target, request, model, port))


@app.command("preview-candidate")
def preview_candidate_command(
    ctx: typer.Context, candidate_file: Path, repo: RepoOption = Path(".")
) -> None:
    """Show one supplied Python file replacement without writing to the repository."""
    _run(ctx, lambda db: _application(ctx, db).preview(repo, candidate_file))


@app.command("verify-candidate")
def verify_candidate_command(
    ctx: typer.Context,
    candidate_file: Path,
    image: Annotated[str, typer.Option("--image", help="Prebuilt immutable Podman image ID.")],
    test: Annotated[list[str], typer.Option("--test", help="Registered pytest path.")],
    repo: RepoOption = Path("."),
) -> None:
    """Run pytest on a candidate in rootless Podman; never approve or apply it."""
    _run(
        ctx,
        lambda db: _application(ctx, db).verify_candidate(repo, candidate_file, image, tuple(test)),
    )


@app.command("apply-candidate")
def apply_candidate_command(
    ctx: typer.Context,
    candidate_file: Path,
    reviewed_hash: Annotated[
        str, typer.Option("--reviewed-hash", help="Candidate hash shown by preview-candidate.")
    ],
    reviewed_source_hash: Annotated[
        str, typer.Option("--reviewed-source-hash", help="Source hash shown by preview-candidate.")
    ],
    reviewed_target_digest: Annotated[
        str,
        typer.Option("--reviewed-target-digest", help="Target digest shown by preview-candidate."),
    ],
    image: Annotated[str, typer.Option("--image", help="Prebuilt immutable Podman image ID.")],
    test: Annotated[list[str], typer.Option("--test", help="Registered pytest path.")],
    repo: RepoOption = Path("."),
) -> None:
    """Explicit experimental one-file apply after a fresh isolated pytest run."""
    _run(
        ctx,
        lambda db: _application(ctx, db).apply_tested_candidate(
            repo, candidate_file, reviewed_hash, reviewed_source_hash,
            reviewed_target_digest, image, tuple(test)
        ),
    )


@app.command("reconcile-write")
def reconcile_write_command(
    ctx: typer.Context,
    attempt_id: str,
    target: str,
    repo: RepoOption = Path("."),
) -> None:
    """Observe an interrupted single-file write; do not retry or approve it."""
    _run(ctx, lambda db: _application(ctx, db).reconcile_write(repo, attempt_id, target))


@app.command()
def profile(ctx: typer.Context, target: str, repo: RepoOption = Path(".")) -> None:
    """Reserved; no host runtime execution fallback is permitted."""
    _pending(ctx, "profile", repo)


@app.command()
def optimize(ctx: typer.Context, target: str, repo: RepoOption = Path(".")) -> None:
    """Reserved; profiling and optimization are not enabled yet."""
    _pending(ctx, "optimize", repo)


@app.command()
def verify(
    ctx: typer.Context,
    repo: RepoOption = Path("."),
    patch: Annotated[str | None, typer.Option()] = None,
    revision: Annotated[int | None, typer.Option(min=1)] = None,
) -> None:
    """Reserved; requires a safe worktree, finalized risk, plan and isolated sandbox."""
    _pending(ctx, "verify", repo)


@app.command()
def apply(
    ctx: typer.Context,
    repo: RepoOption = Path("."),
    patch: Annotated[str | None, typer.Option()] = None,
    revision: Annotated[int | None, typer.Option(min=1)] = None,
) -> None:
    """Reserved; no source modification or automatic approval is performed."""
    _pending(ctx, "apply", repo)


def main() -> None:
    app()
