import unittest
from types import SimpleNamespace

from app.models.schemas import SourceItem
from app.services.answer_renderer import AnswerRenderer
from app.services.evidence_structurer import EvidenceStructurer, StructuredEvidence
from app.services.information_sufficiency import InformationSufficiencyJudge
from app.services.claim_judge import ClaimJudge
from app.services.novelty_judge import NoveltyJudge
from app.services.query_planner import QuestionStructure, QueryIntent, QueryPlan, QueryPlanner


def make_plan(query: str, intent: QueryIntent) -> QueryPlan:
    return QueryPlan(
        original_query=query,
        resolved_query=query,
        search_query=query,
        intent=intent,
        user_goal=query,
        requested_tasks=["직접 답변"],
        confidence=0.9,
    )


class FakeLlmClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.models = []
        self.messages = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature, **kwargs):
        self.models.append(model)
        self.messages.append(messages)
        content = self.responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class InformationSufficiencyJudgeTest(unittest.TestCase):
    def setUp(self):
        self.judge = InformationSufficiencyJudge()

    def test_generic_algorithm_request_asks_for_details(self):
        plan = make_plan(
            "나는 새로운 알고리즘을 만들고싶어 괜찮을까?",
            QueryIntent.NOVELTY_ASSESSMENT,
        )

        assessed = self.judge.assess(plan)

        self.assertTrue(assessed.needs_clarification)
        self.assertFalse(assessed.needs_retrieval)
        self.assertIn("어떤 문제", assessed.clarification_question)

    def test_generic_algorithm_request_cannot_bypass_guard_when_intent_is_wrong(self):
        plan = make_plan(
            "나는 새로운 알고리즘을 만들고싶어 괜찮을까?",
            QueryIntent.FACT_LOOKUP,
        )

        assessed = self.judge.assess(plan)

        self.assertTrue(assessed.needs_clarification)
        self.assertFalse(assessed.needs_retrieval)

    def test_planner_expansion_cannot_invent_missing_algorithm_details(self):
        plan = make_plan(
            "나는 새로운 알고리즘을 만들고싶어 괜찮을까?",
            QueryIntent.NOVELTY_ASSESSMENT,
        ).model_copy(
            update={
                "resolved_query": "커널과 앙상블을 결합한 이상 탐지 알고리즘의 신규성을 평가한다"
            }
        )

        assessed = self.judge.assess(plan)

        self.assertTrue(assessed.needs_clarification)
        self.assertFalse(assessed.needs_retrieval)

    def test_specific_algorithm_change_can_continue(self):
        plan = make_plan(
            "기존 경사하강법에 적응형 모멘텀 업데이트 규칙을 추가하면 새로운 알고리즘일까?",
            QueryIntent.NOVELTY_ASSESSMENT,
        )

        assessed = self.judge.assess(plan)

        self.assertFalse(assessed.needs_clarification)
        self.assertTrue(assessed.needs_retrieval)

    def test_concrete_design_goal_can_continue(self):
        plan = make_plan(
            "반도체 불량 예측을 위한 모델 구조를 설계해줘",
            QueryIntent.DESIGN_PROPOSAL,
        )

        self.assertFalse(self.judge.assess(plan).needs_clarification)


class QueryPlannerFallbackTest(unittest.TestCase):
    def test_greeting_routes_without_retrieval(self):
        plan = QueryPlanner()._fallback_plan("안녕하세요")

        self.assertEqual(QueryIntent.GENERAL_CHAT, plan.intent)
        self.assertFalse(plan.needs_retrieval)

    def test_algorithm_word_alone_does_not_mean_novelty(self):
        plan = QueryPlanner()._fallback_plan("반도체 불량 예측 알고리즘을 만들어줘")

        self.assertEqual(QueryIntent.DESIGN_PROPOSAL, plan.intent)

    def test_llm_cannot_skip_retrieval_for_technical_question(self):
        client = FakeLlmClient([
            '{"primary_intent":"COMPARISON","user_goal":"두 모델 비교",'
            '"resolved_query":"Qwen과 Gemma 비교","entities":["Qwen","Gemma"],'
            '"constraints":[],"sub_questions":[],"requested_tasks":["비교"],'
            '"needs_retrieval":false,"needs_comparison":true,'
            '"needs_clarification":false,"ambiguities":[],'
            '"clarification_question":null,"confidence":0.9}'
        ])

        plan = QueryPlanner().plan(
            "Qwen과 Gemma를 비교해줘", llm_client=client, model="planner-model"
        )

        self.assertEqual(QueryIntent.COMPARISON, plan.intent)
        self.assertTrue(plan.needs_retrieval)

    def test_llm_general_chat_skips_retrieval_even_if_flag_is_true(self):
        client = FakeLlmClient([
            '{"primary_intent":"GENERAL_CHAT","user_goal":"인사에 응답",'
            '"resolved_query":"안녕하세요","entities":[],"constraints":[],'
            '"sub_questions":[],"requested_tasks":["대화"],'
            '"needs_retrieval":true,"needs_comparison":false,'
            '"needs_clarification":false,"ambiguities":[],'
            '"clarification_question":null,"confidence":0.9}'
        ])

        plan = QueryPlanner().plan(
            "안녕하세요", llm_client=client, model="planner-model"
        )

        self.assertEqual(QueryIntent.GENERAL_CHAT, plan.intent)
        self.assertFalse(plan.needs_retrieval)

    def test_llm_fact_misclassification_is_promoted_to_novelty(self):
        client = FakeLlmClient([
            '{"primary_intent":"FACT_LOOKUP","user_goal":"신규성 판단",'
            '"resolved_query":"업데이트 규칙 추가의 신규성","entities":[],'
            '"constraints":[],"sub_questions":[],"requested_tasks":["판단"],'
            '"needs_retrieval":true,"needs_comparison":false,'
            '"needs_clarification":false,"ambiguities":[],'
            '"clarification_question":null,"confidence":0.8}'
        ])

        plan = QueryPlanner().plan(
            "기존 최적화 방식에 새 업데이트 규칙을 추가하면 새로운 알고리즘인가요?",
            llm_client=client,
            model="planner-model",
        )

        self.assertEqual(QueryIntent.NOVELTY_ASSESSMENT, plan.intent)

    def test_llm_fact_misclassification_cannot_bypass_comparison_route(self):
        client = FakeLlmClient([
            '{"primary_intent":"FACT_LOOKUP","user_goal":"차이 확인",'
            '"resolved_query":"선형 회귀와 로지스틱 회귀의 차이","entities":[],'
            '"constraints":[],"sub_questions":[],"requested_tasks":["차이"],'
            '"needs_retrieval":true,"needs_comparison":false,'
            '"needs_clarification":false,"ambiguities":[],'
            '"clarification_question":null,"confidence":0.8}'
        ])

        plan = QueryPlanner().plan(
            "선형 회귀와 로지스틱 회귀의 핵심 차이는?",
            llm_client=client,
            model="planner-model",
        )

        self.assertEqual(QueryIntent.COMPARISON, plan.intent)
        self.assertTrue(plan.needs_comparison)
        self.assertEqual(QuestionStructure.COMPARATIVE, plan.question_structure)
        self.assertTrue(plan.requires_synthesis)


class NoveltyFinalizerTest(unittest.TestCase):
    def test_removes_report_heading_without_inserting_fixed_verdict(self):
        answer = "기술적 가능성: 실제 판단입니다. [근거 1]"
        plan = make_plan("구체적인 설계의 신규성을 판단해줘", QueryIntent.NOVELTY_ASSESSMENT)

        finalized = NoveltyJudge().finalize(answer, plan)

        self.assertEqual("실제 판단입니다. [근거 1]", finalized)
        self.assertNotIn("가능합니다. 다만", finalized)

    def test_removes_exact_duplicate_paragraphs(self):
        answer = "같은 판단입니다. [근거 1]\n\n같은 판단입니다. [근거 1]"
        plan = make_plan("신규성을 판단해줘", QueryIntent.NOVELTY_ASSESSMENT)

        self.assertEqual("같은 판단입니다. [근거 1]", NoveltyJudge().finalize(answer, plan))


class CitationValidationTest(unittest.TestCase):
    def test_removes_claim_when_only_citation_is_not_selected(self):
        answer = "유효한 주장입니다. [근거 1]\n\n잘못된 주장입니다. [근거 99]"

        validated = ClaimJudge().validate_citations(answer, {1, 2})

        self.assertEqual("유효한 주장입니다. [근거 1]", validated)

    def test_quality_check_rejects_empty_invalid_and_internal_output(self):
        judge = ClaimJudge()

        self.assertTrue(judge.quality_issues("", {1}))
        issues = judge.quality_issues("{\"coverage\": \"PARTIAL\"} [근거 99]", {1})

        self.assertTrue(any("선택되지 않은" in issue for issue in issues))
        self.assertTrue(any("구조화" in issue for issue in issues))

    def test_quality_check_accepts_grounded_natural_answer(self):
        issues = ClaimJudge().quality_issues("핵심 차이는 출력 방식입니다. [근거 1]", {1})

        self.assertEqual([], issues)

    def test_partial_answer_must_disclose_missing_scope(self):
        issues = ClaimJudge().quality_issues(
            "관련된 일반 원리는 확인됩니다. [근거 1]",
            {1},
            require_partial_disclosure=True,
        )

        self.assertTrue(any("부분 근거" in issue for issue in issues))

    def test_partial_answer_accepts_explicit_limit(self):
        issues = ClaimJudge().quality_issues(
            "일반 원리는 확인되지만 신규성을 판단할 근거는 부족합니다. [근거 1]",
            {1},
            require_partial_disclosure=True,
        )

        self.assertEqual([], issues)


class EvidenceStructurerTest(unittest.TestCase):
    def setUp(self):
        self.sources = [
            SourceItem(
                source_type="POST",
                source_id=number,
                title=f"문서 {number}",
                category="AI_TECH",
                snippet=f"원문 {number}",
                score=0.8,
                citation_number=number,
            )
            for number in range(1, 4)
        ]
        self.plan = make_plan("두 방법의 차이는?", QueryIntent.COMPARISON)

    def test_uses_planner_model_and_keeps_only_selected_sources(self):
        client = FakeLlmClient([
            '{"answer_focus":"핵심 차이","selected_citations":[2],'
            '"claims":[{"claim":"두 번째 사실","citations":[2],"kind":"FACT"}]}'
        ])
        structurer = EvidenceStructurer()

        structured = structurer.structure(client, "planner-model", self.plan, self.sources)
        selected = structurer.select_sources(structured, self.sources)

        self.assertEqual(["planner-model"], client.models)
        self.assertEqual([2], structured.selected_citations)
        self.assertEqual([2], [source.citation_number for source in selected])

    def test_invalid_citations_fall_back_to_top_two_sources(self):
        client = FakeLlmClient([
            '{"answer_focus":"잘못된 선택","selected_citations":[99],"claims":[]}',
            '{"answer_focus":"잘못된 선택","selected_citations":[99],"claims":[]}',
        ])

        structured = EvidenceStructurer().structure(
            client, "planner-model", self.plan, self.sources
        )

        self.assertEqual([1, 2], structured.selected_citations)
        self.assertEqual("PARTIAL", structured.coverage)
        self.assertTrue(structured.missing_points)

    def test_missing_required_aspect_forces_partial_coverage(self):
        client = FakeLlmClient([
            '{"answer_focus":"핵심 차이","selected_citations":[1,2],'
            '"claims":[],"coverage":"COMPLETE","missing_points":[],'
            '"required_aspects":['
            '{"key":"first_subject","description":"첫 대상","status":"SUPPORTED","citations":[1]},'
            '{"key":"second_subject","description":"둘째 대상","status":"MISSING","citations":[]},'
            '{"key":"material_difference","description":"차이","status":"SUPPORTED","citations":[2]}]}'
        ])

        structured = EvidenceStructurer().structure(
            client, "planner-model", self.plan, self.sources
        )

        self.assertEqual("PARTIAL", structured.coverage)
        self.assertTrue(any(item.status == "MISSING" for item in structured.required_aspects))
        self.assertIn("두 번째 비교 대상의 동일 기준상 특성", structured.missing_points)

    def test_zero_direct_evidence_is_valid_partial_result(self):
        required = EvidenceStructurer.required_aspects(self.plan)
        aspects = ",".join(
            '{"key":"' + key + '","description":"' + description
            + '","status":"MISSING","citations":[]}'
            for key, description in required.items()
        )
        client = FakeLlmClient([
            '{"answer_focus":"비교 불가","selected_citations":[],"claims":[],'
            '"coverage":"PARTIAL","missing_points":["직접 비교 근거가 없음"],'
            '"required_aspects":[' + aspects + ']}'
        ])

        structured = EvidenceStructurer().structure(
            client, "planner-model", self.plan, self.sources
        )

        self.assertEqual([], structured.selected_citations)
        self.assertEqual("PARTIAL", structured.coverage)
        self.assertTrue(all(item.status == "MISSING" for item in structured.required_aspects))


class FinalAnswerRendererTest(unittest.TestCase):
    def test_uses_answer_model_with_selected_original_source(self):
        client = FakeLlmClient(["최종 답변입니다. [근거 2]"])
        structured = StructuredEvidence(
            answer_focus="핵심 차이",
            selected_citations=[2],
            claims=[],
        )
        source = SourceItem(
            source_type="POST",
            source_id=2,
            title="문서 2",
            category="AI_TECH",
            snippet="선택 원문",
            score=0.8,
            citation_number=2,
        )

        answer = AnswerRenderer().generate_final(
            client,
            "answer-model",
            make_plan("차이를 알려줘", QueryIntent.COMPARISON),
            structured,
            [source],
        )

        self.assertEqual("최종 답변입니다. [근거 2]", answer)
        self.assertEqual(["answer-model"], client.models)
        self.assertIn("선택 원문", client.messages[0][1]["content"])


if __name__ == "__main__":
    unittest.main()
