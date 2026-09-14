from dataclasses import dataclass

from kh_agent.core.enums import PatchState
from kh_agent.core.errors import DomainError, ErrorCode


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
