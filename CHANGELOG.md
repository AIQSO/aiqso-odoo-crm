# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2025-12-26

### Added
- Dependabot configuration for automated dependency updates

### Changed
- Updated GitHub Actions: checkout v4→v6, setup-python v5→v6, cache v4→v5, setup-uv v4→v7

## [0.5.0] - 2025-12-26

### Added
- Makefile for common development commands (`make dev`, `make test`, `make check`, etc.)

### Changed
- Updated README with Makefile usage and Development section
- Simplified Quick start instructions to use `make dev`

## [0.4.0] - 2025-12-26

### Added
- Unit tests for `scripts/import_lead_list.py` with 83% coverage (32 tests)
- Unit tests for `scripts/sync_enriched_leads.py` with 86% coverage (43 tests)
- Unit tests for `scripts/import_commercial_leads.py` with 92% coverage (49 tests)
- Total test count: 144 tests with 87% overall coverage

### Changed
- Comprehensive test coverage for all major script modules
- Improved mock patterns for XML-RPC and PostgreSQL connections

## [0.3.0] - 2025-12-26

### Added
- Unit tests for `scripts/config.py` with 100% coverage (20 tests)
- Code coverage reporting with pytest-cov
- Codecov integration for coverage tracking
- CI and Codecov badges in README

### Changed
- CI pipeline now runs coverage on Python 3.11 and uploads to Codecov
- Added test-specific ruff ignores (S101, S105, S106)

## [0.2.0] - 2025-12-26

### Added
- `pyproject.toml` with project configuration consolidating all tool settings
- `.pre-commit-config.yaml` with pre-commit hooks:
  - Standard hooks (trailing-whitespace, end-of-file-fixer, check-yaml, check-json)
  - Ruff linting and formatting
  - MyPy type checking (non-blocking)
- `.github/workflows/ci.yml` with CI pipeline:
  - Lint job (ruff check + format)
  - Type check job (mypy, continues on error)
  - Test job with Python 3.10/3.11/3.12 matrix
  - Proper dependency caching with uv

### Changed
- Migrated from `requirements.txt` to `pyproject.toml` for dependency management
- Updated all scripts to use modern Python 3.10+ type annotations
- Reformatted all code with ruff formatter (double quotes, consistent styling)
- Fixed bare `except` clauses to use `except ValueError` for specificity
- Removed unused variable assignment in `import_commercial_leads.py`
- Expanded `.gitignore` with comprehensive Python dev tooling patterns

### Fixed
- 36 linting issues across all scripts (ruff auto-fixed 34, 2 manual fixes)
- Import sorting across all modules (isort via ruff)
- Deprecated typing imports (`Dict`, `List`, `Optional`) replaced with modern syntax

## [0.1.0] - 2025-12-18

### Added
- Initial repository setup with security improvements
- `scripts/import_lead_list.py`: Import single lead list CSV
- `scripts/import_commercial_leads.py`: Import multi-city commercial leads
- `scripts/sync_enriched_leads.py`: Sync enriched contact details from PostgreSQL
- `scripts/config.py`: Configuration loader for Odoo/PostgreSQL credentials
- Documentation: `README.md`, `ARCHITECTURE.md`, `CLAUDE.md`
- `docs/CONFIGURATION.md`: Configuration reference
- `docs/LEAD_LIST_STRUCTURE.md`: Lead list organization documentation

### Security
- Removed hardcoded Odoo/Postgres credentials; load via environment variables or CLI
- Added `.env.example` template for secure credential management
- Added `.gitignore` to prevent committing secrets and local artifacts

### Changed
- Added Odoo field validation in `sync_enriched_leads.py` using `fields_get` before writes
