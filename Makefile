.PHONY: test audit

test:
	.venv/bin/python -m pytest tests/ -x -q

audit:
	.venv/bin/pip-audit
