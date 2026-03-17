import pytest

from odigos.core.classifier import QueryAnalysis, QueryClassifier


class TestHeuristic:
    def test_heuristic_simple(self):
        c = QueryClassifier()
        assert c._classify_heuristic("hi") == "simple"

    def test_heuristic_simple_thanks(self):
        c = QueryClassifier()
        assert c._classify_heuristic("thanks") == "simple"

    def test_heuristic_document(self):
        c = QueryClassifier()
        assert c._classify_heuristic("search the document for Holmes") == "document_query"

    def test_heuristic_complex(self):
        c = QueryClassifier()
        assert c._classify_heuristic("compare chapter 1 and chapter 2 step by step") == "complex"

    def test_heuristic_planning(self):
        c = QueryClassifier()
        assert c._classify_heuristic("create a plan for the project") == "planning"

    def test_heuristic_uncertain(self):
        c = QueryClassifier()
        assert c._classify_heuristic("what's the weather in Paris") is None

    def test_heuristic_specificity(self):
        c = QueryClassifier()
        assert c._classify_heuristic("hi, search the document") == "document_query"


class TestClassify:
    @pytest.mark.asyncio
    async def test_classify_fallback_no_provider(self):
        c = QueryClassifier(provider=None)
        result = await c.classify("what's the weather in Paris")
        assert result.classification == "standard"
        assert result.confidence == 0.5
        assert result.tier == 2

    def test_query_analysis_fields(self):
        qa = QueryAnalysis(
            classification="complex",
            confidence=0.9,
            entities=["chapter 1"],
            search_queries=["chapter comparison"],
            sub_questions=["what is in chapter 1?"],
            tier=2,
        )
        assert qa.classification == "complex"
        assert qa.confidence == 0.9
        assert qa.entities == ["chapter 1"]
        assert qa.search_queries == ["chapter comparison"]
        assert qa.sub_questions == ["what is in chapter 1?"]
        assert qa.tier == 2
