import pytest

from odigos.core.classifier import QueryAnalysis, QueryClassifier, _parse_rules


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


class TestRulesParsing:
    def test_rules_parsing(self):
        raw = (
            "---\npriority: 5\nalways_include: false\n---\n"
            "[document_query]\n"
            "in the document, in the file\n\n"
            "[complex]\n"
            "compare, step by step\n\n"
            "[planning]\n"
            "plan for, schedule\n\n"
            "[simple]\n"
            "hi, hello\n"
        )
        rules = _parse_rules(raw)
        assert rules["document_query"] == ["in the document", "in the file"]
        assert rules["complex"] == ["compare", "step by step"]
        assert rules["planning"] == ["plan for", "schedule"]
        assert rules["simple"] == ["hi", "hello"]

    def test_rules_parsing_no_frontmatter(self):
        raw = "[simple]\nhi, hello, bye\n"
        rules = _parse_rules(raw)
        assert rules["simple"] == ["hi", "hello", "bye"]

    def test_rules_parsing_empty_raises(self):
        with pytest.raises(ValueError, match="No rules parsed"):
            _parse_rules("")

    def test_rules_fallback(self):
        """When file missing, _load_rules returns hardcoded fallback rules."""
        rules = QueryClassifier._load_rules()
        assert "document_query" in rules
        assert "complex" in rules
        assert "planning" in rules
        assert "simple" in rules
        assert len(rules["document_query"]) > 0


class TestSimilarityHint:
    def test_similarity_hint_field(self):
        qa = QueryAnalysis(
            classification="standard",
            confidence=0.8,
            similarity_hint="Similar past query classified as 'document_query' with good results",
        )
        assert qa.similarity_hint is not None
        assert "document_query" in qa.similarity_hint

    def test_similarity_hint_default_none(self):
        qa = QueryAnalysis(classification="simple", confidence=1.0)
        assert qa.similarity_hint is None
