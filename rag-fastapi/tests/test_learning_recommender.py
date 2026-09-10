import unittest
from types import SimpleNamespace

from app.models.schemas import AccessScope, LearningDirectionRequest, SourceItem
from app.services.evidence_retriever import EvidenceBundle
from app.services.learning_recommender import LearningRecommender
from app.services.web_search import WebSearchResult, WebSearchService


class FakeLlmClient:
    def __init__(self, content):
        self.content = content
        self.chat = SimpleNamespace(completions=self)

    def create(self, **_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeRetriever:
    def __init__(self, sources):
        self.sources = sources
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return EvidenceBundle(self.sources, "context" if self.sources else "")


class FakeWebSearch:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search(self, query, limit=None):
        self.queries.append((query, limit))
        return self.results


def request(**updates):
    values = {
        "post_id": 7,
        "title": "Hybrid Search 정리",
        "content": "이 글은 dense 검색과 BM25의 기본 개념을 충분히 설명한다.",
        "category": "AI_TECH",
        "access_scope": AccessScope(user_id=3, roles=["ROLE_USER"]),
    }
    values.update(updates)
    return LearningDirectionRequest(**values)


class LearningRecommenderTest(unittest.TestCase):
    llm_json = (
        '{"gaps":[{"topic":"RRF 가중치 튜닝","reason":"점수 결합 실험이 없다",'
        '"search_query":"reciprocal rank fusion weight tuning"}]}'
    )

    def test_internal_source_is_used_before_web_and_current_post_is_excluded(self):
        internal = SourceItem(
            source_type="POST",
            source_id=11,
            title="RRF 실험",
            category="AI_TECH",
            url="/posts/11",
            snippet="RRF 가중치 비교 실험",
            score=0.9,
            citation_number=1,
        )
        retriever = FakeRetriever([internal])
        web = FakeWebSearch([])
        recommender = LearningRecommender(FakeLlmClient(self.llm_json), retriever, web)

        response = recommender.recommend(request())

        self.assertEqual("INTERNAL", response.recommendations[0].evidence_status)
        self.assertEqual([], web.queries)
        self.assertEqual([("POST", 7)], retriever.calls[0]["excluded_sources"])
        self.assertEqual(3, retriever.calls[0]["access_scope"].user_id)

    def test_web_is_only_used_when_internal_search_is_empty(self):
        checked_at = "2026-09-10T00:00:00+00:00"
        web = FakeWebSearch([WebSearchResult(
            title="RRF paper",
            url="https://example.edu/rrf",
            publisher="example.edu",
            snippet="Original paper",
            score=0.9,
            checked_at=checked_at,
        )])
        recommender = LearningRecommender(
            FakeLlmClient(self.llm_json), FakeRetriever([]), web
        )

        response = recommender.recommend(request())

        self.assertTrue(response.web_search_used)
        self.assertEqual("WEB", response.recommendations[0].evidence_status)
        self.assertEqual(checked_at, response.sources[0].checked_at)

    def test_missing_sources_are_explicitly_labeled_as_idea(self):
        recommender = LearningRecommender(
            FakeLlmClient(self.llm_json), FakeRetriever([]), FakeWebSearch([])
        )

        response = recommender.recommend(request())

        self.assertEqual("IDEA", response.recommendations[0].evidence_status)
        self.assertEqual([], response.recommendations[0].citation_numbers)

    def test_checked_item_is_preserved_by_stable_id(self):
        item_id = LearningRecommender.recommendation_id("RRF 가중치 튜닝")
        recommender = LearningRecommender(
            FakeLlmClient(self.llm_json), FakeRetriever([]), FakeWebSearch([])
        )

        response = recommender.recommend(request(checked_direction_ids=[item_id]))

        self.assertTrue(response.recommendations[0].checked)


class WebSearchPolicyTest(unittest.TestCase):
    def test_primary_sources_rank_above_unclassified_domains(self):
        self.assertGreater(
            WebSearchService.authority_score("docs.python.org"),
            WebSearchService.authority_score("random-blog.example"),
        )

    def test_tracking_parameters_are_removed(self):
        value = WebSearchService._canonical_url(
            "https://example.edu/paper?utm_source=x&id=3#abstract"
        )
        self.assertEqual("https://example.edu/paper?id=3", value)


if __name__ == "__main__":
    unittest.main()
