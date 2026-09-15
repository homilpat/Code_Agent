from dataclasses import dataclass

from kh_agent.core.canonical import ContentHash
from kh_agent.core.enums import CheckStatus, PatchState
from kh_agent.core.errors import DomainError, ErrorCode

TRANSITIONS: dict[PatchState, frozenset[PatchState]] = {
    PatchState.PROPOSED: frozenset({PatchState.APPLIED_TO_WORKTREE, PatchState.PATCH_APPLY_FAILED}),
    PatchState.APPLIED_TO_WORKTREE: frozenset({PatchState.VERIFYING}),
    PatchState.VERIFYING: frozenset(
        {PatchState.VERIFIED, PatchState.FAILED, PatchState.INCONCLUSIVE}
    ),
    PatchState.VERIFIED: frozenset({PatchState.APPROVED, PatchState.STALE_VERIFICATION}),
    PatchState.APPROVED: frozenset(
        {PatchState.APPLIED, PatchState.VERIFIED, PatchState.STALE_VERIFICATION}
    ),
    PatchState.INCONCLUSIVE: frozenset({PatchState.VERIFYING}),
}


def require_transition(before: PatchState, after: PatchState) -> None:
    if after not in TRANSITIONS.get(before, frozenset()):
        raise DomainError(ErrorCode.INVALID_STATE_TRANSITION)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    required: bool
    evidence_hash: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.status, CheckStatus)
            or type(self.required) is not bool
            or not self.name
            or len(self.name) > 200
        ):
            raise DomainError(ErrorCode.INVALID_INPUT, "Invalid verification check")
        if self.evidence_hash:
            ContentHash(self.evidence_hash, "check-evidence-v1")


def verification_outcome(checks: tuple[CheckResult, ...]) -> PatchState:
    required = [check for check in checks if check.required]
    if len({check.name for check in checks}) != len(checks):
        raise DomainError(ErrorCode.INVALID_INPUT, "Duplicate verification check")
    if any(check.status == CheckStatus.FAIL for check in required):
        return PatchState.FAILED
    # A required check must PASS with evidence. NOT_APPLICABLE would need a trusted
    # applicability predicate (CONDITIONAL requiredness) that plans cannot express yet,
    # so a caller-supplied reference can no longer exempt a required check.
    if not required or any(
        check.status != CheckStatus.PASS or not check.evidence_hash for check in required
    ):
        return PatchState.INCONCLUSIVE
    return PatchState.VERIFIED
