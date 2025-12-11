PYTHON ?= python
POETRY ?= poetry

.PHONY: test test-cov

test:
	$(POETRY) run pytest

test-cov:
	$(POETRY) run pytest --cov=app --cov-report=term-missing
