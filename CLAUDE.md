# CLAUDE.md

This file contains project-specific context and instructions for Claude.

## Project Overview
Damai.com automated ticket purchasing system based on uiautomator2 (ATX).
See `docs/ARCHITECTURE.md` for full technical architecture and changelog.

## Project Structure
- `src/ticket_purchase/` — Main source code (modular: connection, detector, executor, workflow, etc.)
- `config/` — Configuration files (.env for device, config.yaml for business)
- `docs/` — Architecture doc and design plans

## Commands
- Run: `python -m ticket_purchase.main --config config/config.yaml`
- Run immediately: `python -m ticket_purchase.main --now`
- Run via Docker: `./start.sh --docker`
- Run tests: `uv run pytest`

## Development Guidelines
- Use uv for dependency management
- Python 3.12+
- loguru for logging (no print statements)
- Follow existing module patterns in src/ticket_purchase/