import pytest
import jsonschema

from odigos.core.executor import _coerce_and_validate


class TestCoerceAndValidate:
    def test_boolean_coercion_true(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _coerce_and_validate({"flag": "true"}, schema)
        assert result["flag"] is True

    def test_boolean_coercion_false(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _coerce_and_validate({"flag": "false"}, schema)
        assert result["flag"] is False

    def test_integer_coercion(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = _coerce_and_validate({"count": "42"}, schema)
        assert result["count"] == 42

    def test_number_coercion(self):
        schema = {"type": "object", "properties": {"rate": {"type": "number"}}}
        result = _coerce_and_validate({"rate": "3.14"}, schema)
        assert result["rate"] == 3.14

    def test_string_passthrough(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = _coerce_and_validate({"name": "hello"}, schema)
        assert result["name"] == "hello"

    def test_enum_validation_passes(self):
        schema = {"type": "object", "properties": {"ratio": {"type": "string", "enum": ["1:1", "4:3"]}}}
        result = _coerce_and_validate({"ratio": "1:1"}, schema)
        assert result["ratio"] == "1:1"

    def test_enum_validation_rejects(self):
        schema = {"type": "object", "properties": {"ratio": {"type": "string", "enum": ["1:1", "4:3"]}}}
        with pytest.raises(jsonschema.ValidationError):
            _coerce_and_validate({"ratio": "invalid"}, schema)

    def test_required_field_rejects(self):
        schema = {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}
        with pytest.raises(jsonschema.ValidationError):
            _coerce_and_validate({}, schema)

    def test_unknown_keys_pass_through(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = _coerce_and_validate({"a": "ok", "b": "extra"}, schema)
        assert result["b"] == "extra"

    def test_does_not_mutate_original(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        original = {"flag": "true"}
        _coerce_and_validate(original, schema)
        assert original["flag"] == "true"

    def test_invalid_integer_caught_by_validation(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        with pytest.raises(jsonschema.ValidationError):
            _coerce_and_validate({"count": "not_a_number"}, schema)
