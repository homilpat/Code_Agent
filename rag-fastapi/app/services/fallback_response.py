from collections.abc import Sequence


def partial_evidence_message(
    *,
    has_sources: bool,
    missing_points: Sequence[str] | None = None,
) -> str:
    """Return a user-facing fallback without duplicating evidence-card content."""
    missing = [item.strip() for item in (missing_points or []) if item.strip()]

    if not has_sources:
        if missing:
            return (
                "현재 저장된 자료만으로는 질문에 충분히 답하기 어렵습니다. "
                "확인이 더 필요한 내용은 "
                + ", ".join(missing)
                + "입니다. 관련 정보를 보강하거나 질문을 조금 더 구체적으로 알려주세요."
            )
        return (
            "현재 저장된 자료만으로는 질문에 충분히 답하기 어렵습니다. "
            "관련 자료를 보강하거나 질문을 조금 더 구체적으로 알려주세요."
        )

    if missing:
        return (
            "관련 원문은 찾았지만 답변을 확정하기에는 근거가 충분하지 않습니다. "
            "아래 근거 카드에서 확인 가능한 범위를 살펴보고, "
            + ", ".join(missing)
            + "에 관한 정보를 보완해주세요."
        )

    return (
        "관련 원문은 찾았지만 검증 기준을 통과한 답변을 완성하지 못했습니다. "
        "아래 근거 카드를 확인하거나 질문을 조금 더 구체적으로 알려주세요."
    )


def generation_unavailable_message(*, has_sources: bool) -> str:
    if has_sources:
        return (
            "관련 원문은 찾았지만 현재 답변 생성 모델에 연결하지 못했습니다. "
            "원문은 아래 근거 카드에서 확인할 수 있으며, 잠시 후 다시 시도해주세요."
        )
    return (
        "현재 답변 생성 모델에 연결하지 못했습니다. 잠시 후 다시 시도해주세요."
    )
