.PHONY: install format lint check test

install:  ## Install the package in editable mode with dev tools
	uv pip install -e ".[dev]"

format:  ## Sort imports and format the code
	ruff check --select I --fix .
	ruff format .

lint:  ## Report lint issues
	ruff check .

check:  ## Verify formatting and lint without changing files (for CI)
	ruff format --check .
	ruff check .

test:  ## Run the test suite
	pytest
