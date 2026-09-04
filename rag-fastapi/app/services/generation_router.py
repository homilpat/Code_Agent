from dataclasses import dataclass

from app.services.query_planner import QuestionStructure, QueryPlan


@dataclass(frozen=True)
class GenerationDecision:
    mode: str
    reason: str


class GenerationRouter:
    """Choose the cheap or high-assurance generation path from plan signals."""

    HIERARCHICAL_STRUCTURES = {
        QuestionStructure.COMPARATIVE,
        QuestionStructure.CAUSAL,
        QuestionStructure.PROCEDURAL,
        QuestionStructure.SYNTHESIS,
        QuestionStructure.JUDGMENT,
    }

    def decide(self, plan: QueryPlan, requested_mode: str) -> GenerationDecision:
        if requested_mode in {"qwen_direct", "hierarchical"}:
            return GenerationDecision(requested_mode, "explicit evaluation override")

        signals = [f"structure {plan.question_structure.value}"]
        if plan.requires_synthesis:
            signals.append("evidence synthesis required")
        if plan.requires_judgment:
            signals.append("judgment required")

        if (
            plan.question_structure in self.HIERARCHICAL_STRUCTURES
            or plan.requires_synthesis
            or plan.requires_judgment
        ):
            return GenerationDecision("hierarchical", "; ".join(signals))
        return GenerationDecision(
            "qwen_direct",
            f"structure {plan.question_structure.value}; direct evidence lookup",
        )


generation_router = GenerationRouter()
