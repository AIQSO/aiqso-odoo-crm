.PHONY: help install dev clean lint format typecheck test coverage check all

# Default Python interpreter
PYTHON := python3
VENV := venv
BIN := $(VENV)/bin

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# =============================================================================
# Environment Setup
# =============================================================================

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

install: $(VENV)/bin/activate ## Install production dependencies
	$(BIN)/pip install -e .

dev: $(VENV)/bin/activate ## Install development dependencies
	$(BIN)/pip install -e ".[dev]"
	$(BIN)/pre-commit install

# =============================================================================
# Code Quality
# =============================================================================

lint: ## Run ruff linter
	$(BIN)/ruff check .

lint-fix: ## Run ruff linter with auto-fix
	$(BIN)/ruff check --fix .

format: ## Check code formatting
	$(BIN)/ruff format --check .

format-fix: ## Auto-format code
	$(BIN)/ruff format .

typecheck: ## Run mypy type checker
	$(BIN)/mypy scripts/

check: lint format typecheck ## Run all code quality checks

# =============================================================================
# Testing
# =============================================================================

test: ## Run tests
	$(BIN)/pytest tests/ -v

coverage: ## Run tests with coverage report
	$(BIN)/pytest tests/ -v --cov=scripts --cov-report=term-missing --cov-report=html

coverage-xml: ## Run tests with XML coverage (for CI)
	$(BIN)/pytest tests/ -v --cov=scripts --cov-report=xml --cov-report=term-missing

# =============================================================================
# Pre-commit
# =============================================================================

pre-commit: ## Run pre-commit on all files
	$(BIN)/pre-commit run --all-files

pre-commit-install: ## Install pre-commit hooks
	$(BIN)/pre-commit install

# =============================================================================
# Cleaning
# =============================================================================

clean: ## Remove build artifacts and cache files
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf coverage.xml
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

clean-all: clean ## Remove venv and all generated files
	rm -rf $(VENV)

# =============================================================================
# Combined Targets
# =============================================================================

all: dev check test ## Setup dev environment and run all checks

ci: lint format typecheck coverage-xml ## Run CI pipeline locally
