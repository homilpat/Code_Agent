from dataclasses import dataclass
from typing import TYPE_CHECKING

from kh_agent.core.enums import PatchState
from kh_agent.core.errors import DomainError, ErrorCode

if TYPE_CHECKING:
    from kh_agent.repository.safe_git import TargetSnapshot


@dataclass(frozen=True)
class MutationContext:
    head_state: str
    branch: str | None
    commit: str | None
    git_operation_state: str
    dirty: bool | None


def require_normal_mutation(context: MutationContext) -> None:
    if (
        context.head_state != "NORMAL"
        or not context.branch
        or not context.commit
        or context.git_operation_state != "NORMAL"
    ):
        raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED)
    if context.dirty is not False:
        raise DomainError(ErrorCode.DIRTY_WORKTREE_BLOCKED)


def require_mutation_target(snapshot: "TargetSnapshot") -> None:
    """A mutation command needs a Safe Git target that is normal, clean and fully inspected."""
    head = snapshot.evidence["head"]
    require_normal_mutation(
        MutationContext(
            head["head_state"],
            head["branch"],
            head["commit_sha"],
            "IN_PROGRESS" if snapshot.evidence["git_operations"] else "NORMAL",
            snapshot.evidence["worktree"]["dirty"],
        )
    )
    # Uncertain comparisons, sparse/partial/blocked object state and replace refs.
    if not snapshot.mutation_ready:
        raise DomainError(ErrorCode.REPOSITORY_STATE_BLOCKED, "Target is not fully inspectable")


@dataclass(frozen=True)
class VerificationReadiness:
    state: PatchState
    change_set_complete: bool
    post_apply_guardrail: str
    final_risk_reference: str | None
    verification_plan_reference: str | None

    def require(self) -> None:
        if (
            self.state not in (PatchState.APPLIED_TO_WORKTREE, PatchState.INCONCLUSIVE)
            or not self.change_set_complete
            or self.post_apply_guardrail != "ALLOW"
            or not self.final_risk_reference
            or not self.verification_plan_reference
        ):
            raise DomainError(ErrorCode.PATCH_NOT_READY_FOR_VERIFICATION)


def select_revision(
    candidates: list[tuple[str, int]], patch_id: str | None = None, revision: int | None = None
) -> tuple[str, int]:
    if revision is not None and (not patch_id or revision < 1):
        raise DomainError(ErrorCode.INVALID_INPUT, "Revision requires a patch identifier")
    eligible = [
        item
        for item in candidates
        if (patch_id is None or item[0] == patch_id) and (revision is None or item[1] == revision)
    ]
    if len(eligible) > 1:
        raise DomainError(ErrorCode.AMBIGUOUS_PATCH_SELECTION)
    if not eligible:
        raise DomainError(ErrorCode.PATCH_NOT_READY_FOR_VERIFICATION)
    return eligible[0]
