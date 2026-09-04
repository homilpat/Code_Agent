import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.models.schemas import QueryRequest, QueryResponse
from app.services.evidence_retriever import EvidenceRetriever
from app.services.generation_router import GenerationRouter
from app.services.evaluation_report import EvaluationReportService
from app.services.query_planner import QuestionStructure, QueryIntent, QueryPlan
from app.services.retrieval_strategies import BM25Ranker, RankedHit
from evaluation.run_evaluation import (
    expected_generation_mode,
    expected_question_structure,
    source_metrics,
    summarize_by_structure,
    summarize_routing,
    trace_question_structure,
)


class GoldenDatasetTest(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / "evaluation" / "golden_dataset.json"
        self.dataset = json.loads(path.read_text(encoding="utf-8"))

    def test_has_exactly_fifty_unique_cases(self):
        cases = self.dataset["cases"]

        self.assertEqual(50, len(cases))
        self.assertEqual(50, len({case["id"] for case in cases}))

    def test_each_case_has_evaluable_contract(self):
        for case in self.dataset["cases"]:
            self.assertTrue(case["query"].strip())
            self.assertIn(
                case["expected_behavior"],
                {"ANSWER", "PARTIAL", "NO_EVIDENCE", "CLARIFY", "CHAT"},
            )
            self.assertIsInstance(case["expected_source_ids"], list)
            self.assertIsInstance(case["required_terms"], list)


class RetrievalStrategyTest(unittest.TestCase):
    def test_bm25_prioritizes_exactly_relevant_payload(self):
        points = [
            SimpleNamespace(id="1", payload={"title": "CNN", "content": "합성곱 필터와 풀링"}),
            SimpleNamespace(id="2", payload={"title": "GraphRAG", "content": "다중 홉 그래프 탐색"}),
        ]

        ranked = BM25Ranker().rank("그래프 다중 홉 탐색", points, 2)

        self.assertEqual("2", ranked[0].id)

    def test_source_metrics_calculate_hit_recall_and_mrr(self):
        metrics = source_metrics([7, 13], [{"source_id": 4}, {"source_id": 13}])

        self.assertEqual(1.0, metrics["hit_at_k"])
        self.assertEqual(0.5, metrics["recall_at_k"])
        self.assertEqual(0.5, metrics["mrr"])

    def test_hybrid_does_not_apply_cosine_threshold_to_rrf_score(self):
        payload = {
            "source_type": "POST",
            "source_id": 13,
            "title": "GraphRAG",
            "category_section": "AI_TECH",
            "content": "그래프 다중 홉 탐색",
            "chunk_index": 0,
        }

        class FakeStore:
            def search(self, **_kwargs):
                return [RankedHit("chunk-1", payload, 0.8)]

            def scroll_payloads(self, **_kwargs):
                return [SimpleNamespace(id="chunk-1", payload=payload)]

        plan = QueryPlan(
            original_query="그래프 다중 홉",
            resolved_query="그래프 다중 홉",
            search_query="그래프 다중 홉",
            intent=QueryIntent.FACT_LOOKUP,
            user_goal="원리 확인",
        )
        retriever = EvidenceRetriever(FakeStore(), lambda _query: [0.0], min_score=0.5)

        bundle = retriever.retrieve(plan, top_k=1, domain_filter=None, retrieval_mode="hybrid")

        self.assertEqual([13], [source.source_id for source in bundle.sources])
        self.assertEqual(1.0, bundle.sources[0].score)


class QueryContractTest(unittest.TestCase):
    def test_evaluation_modes_are_validated(self):
        request = QueryRequest(
            query="테스트",
            retrieval_mode="hybrid",
            generation_mode="qwen_direct",
        )

        self.assertEqual("hybrid", request.retrieval_mode)
        self.assertEqual("qwen_direct", request.generation_mode)

        with self.assertRaises(Exception):
            QueryRequest(query="테스트", retrieval_mode="unknown")

    def test_auto_is_the_default_generation_mode(self):
        self.assertEqual("auto", QueryRequest(query="테스트").generation_mode)


class GenerationRouterTest(unittest.TestCase):
    @staticmethod
    def plan(intent: QueryIntent, **kwargs):
        return QueryPlan(
            original_query="질문",
            resolved_query="질문",
            search_query="질문",
            intent=intent,
            user_goal="답변",
            **kwargs,
        )

    def test_simple_fact_uses_qwen_direct(self):
        decision = GenerationRouter().decide(
            self.plan(
                QueryIntent.FACT_LOOKUP,
                requested_tasks=["정의", "의미"],
            ),
            "auto",
        )
        self.assertEqual("qwen_direct", decision.mode)

    def test_comparison_uses_hierarchical_path(self):
        decision = GenerationRouter().decide(
            self.plan(
                QueryIntent.COMPARISON,
                question_structure=QuestionStructure.COMPARATIVE,
                requires_synthesis=True,
            ),
            "auto",
        )
        self.assertEqual("hierarchical", decision.mode)

    def test_explicit_ab_override_is_preserved(self):
        decision = GenerationRouter().decide(
            self.plan(QueryIntent.COMPARISON), "qwen_direct"
        )
        self.assertEqual("qwen_direct", decision.mode)

    def test_inferred_synthesis_uses_hierarchical_path(self):
        decision = GenerationRouter().decide(
            self.plan(
                QueryIntent.FACT_LOOKUP,
                question_structure=QuestionStructure.SYNTHESIS,
                requires_synthesis=True,
            ),
            "auto",
        )
        self.assertEqual("hierarchical", decision.mode)


class EvaluationAnalysisTest(unittest.TestCase):
    def test_expected_route_uses_golden_intent_and_behavior(self):
        self.assertEqual(
            "qwen_direct",
            expected_generation_mode({"expected_intent": "FACT_LOOKUP", "expected_behavior": "ANSWER"}),
        )
        self.assertEqual(
            "hierarchical",
            expected_generation_mode({"expected_intent": "CAUSE_ANALYSIS", "expected_behavior": "ANSWER"}),
        )
        self.assertEqual(
            "bypass",
            expected_generation_mode({"expected_intent": "FACT_LOOKUP", "expected_behavior": "CLARIFY"}),
        )
        self.assertEqual(
            "SYNTHESIS",
            expected_question_structure({"expected_intent": "DESIGN_PROPOSAL"}),
        )

    def test_structure_is_read_from_planner_trace(self):
        response = {
            "trace": [{
                "name": "question_planning",
                "detail": "CAUSE_ANALYSIS / CAUSAL; synthesis=True; judgment=False",
            }]
        }
        self.assertEqual("CAUSAL", trace_question_structure(response))

    def test_routing_summary_counts_each_failure_type(self):
        rows = [
            {
                "routing_correct": True,
                "intent_correct": True,
                "structure_correct": True,
                "question_structure": "DIRECT_LOOKUP",
                "expected_question_structure": "DIRECT_LOOKUP",
                "generation_mode": "qwen_direct",
                "expected_generation_mode": "qwen_direct",
            },
            {
                "routing_correct": False,
                "intent_correct": False,
                "structure_correct": False,
                "question_structure": "DIRECT_LOOKUP",
                "expected_question_structure": "CAUSAL",
                "generation_mode": "qwen_direct",
                "expected_generation_mode": "hierarchical",
            },
            {
                "routing_correct": False,
                "intent_correct": True,
                "structure_correct": True,
                "question_structure": "DIRECT_LOOKUP",
                "expected_question_structure": "DIRECT_LOOKUP",
                "generation_mode": "hierarchical",
                "expected_generation_mode": "qwen_direct",
            },
            {
                "routing_correct": False,
                "intent_correct": True,
                "structure_correct": True,
                "question_structure": "CONVERSATIONAL",
                "expected_question_structure": "CONVERSATIONAL",
                "generation_mode": "qwen_direct",
                "expected_generation_mode": "bypass",
            },
        ]

        summary = summarize_routing(rows)

        self.assertEqual(0.25, summary["accuracy"])
        self.assertEqual(1, summary["wrong_direct"])
        self.assertEqual(1, summary["unnecessary_hierarchical"])
        self.assertEqual(1, summary["missed_bypass"])

    def test_structure_summary_includes_quality_and_selected_routes(self):
        row = {
            "expected_question_structure": "CAUSAL",
            "generation_mode": "hierarchical",
            "passed": True,
            "accuracy": 1.0,
            "term_coverage": 1.0,
            "grounded_block_ratio": 1.0,
            "citation_validity": 1.0,
            "latency_ms": 100,
        }

        summary = summarize_by_structure([row])["CAUSAL"]

        self.assertEqual(1, summary["summary"]["cases"])
        self.assertEqual(1, summary["selected_routes"]["hierarchical"])


class EvaluationReportServiceTest(unittest.TestCase):
    def test_dashboard_response_excludes_large_case_answers_and_traces(self):
        report = {
            "status": "complete",
            "dataset_cases": 50,
            "retrieval": {"profiles": {"dense": {"summary": {"cases": 50}, "cases": [{"answer": "large"}]}}},
            "generation": {"profiles": {"auto:dense": {"summary": {"cases": 50}, "cases": [{"trace": ["large"]}]}}},
            "regressions": [{"profile": "auto:dense", "id": "x", "query": "q", "answer": "large", "trace": ["large"]}],
            "analysis": {"auto_routing": {"accuracy": 0.8}},
        }
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "latest.json").write_text(
                json.dumps(report), encoding="utf-8"
            )
            compact = EvaluationReportService(directory).latest()

        self.assertNotIn("cases", compact["generation"]["profiles"]["auto:dense"])
        self.assertNotIn("answer", compact["regressions"][0])
        self.assertNotIn("trace", compact["regressions"][0])
        self.assertEqual(0.8, compact["analysis"]["auto_routing"]["accuracy"])

if __name__ == "__main__":
    unittest.main()
