import pytest
from odigos.skills.code_validator import validate_skill_code


def test_valid_code():
    code = "def run(x: str) -> str:\n    return x\n"
    errors = validate_skill_code(code, {"x": {"type": "string"}})
    assert errors == []


def test_missing_run():
    code = "def helper():\n    pass\n"
    errors = validate_skill_code(code, {})
    assert any("run" in e for e in errors)


def test_syntax_error():
    code = "def run(x:\n    return x\n"
    errors = validate_skill_code(code, {"x": {}})
    assert any("Syntax error" in e for e in errors)


def test_blocked_import_os():
    code = "import os\ndef run():\n    pass\n"
    errors = validate_skill_code(code, {})
    assert any("os" in e for e in errors)


def test_blocked_import_subprocess():
    code = "import subprocess\ndef run():\n    pass\n"
    errors = validate_skill_code(code, {})
    assert any("subprocess" in e for e in errors)


def test_blocked_from_import():
    code = "from os import system\ndef run():\n    pass\n"
    errors = validate_skill_code(code, {})
    assert any("os" in e for e in errors)


def test_blocked_eval_call():
    code = "def run(x: str):\n    return eval(x)\n"
    errors = validate_skill_code(code, {"x": {}})
    assert any("eval" in e for e in errors)


def test_parameter_mismatch():
    code = "def run(x: str):\n    return x\n"
    errors = validate_skill_code(code, {"y": {"type": "string"}})
    assert any("match" in e or "args" in e for e in errors)


def test_no_params_no_args():
    code = "def run():\n    return 'hello'\n"
    errors = validate_skill_code(code, {})
    assert errors == []


def test_async_run_allowed():
    code = "async def run(name: str) -> str:\n    return name\n"
    errors = validate_skill_code(code, {"name": {"type": "string"}})
    assert errors == []
