# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Workman is a Python CLI tool (`wm`) for managing a workspace — a top-level folder containing multiple subproject folders. Subprojects may be git repos, dockerized projects, or both. Full specification is in INSTRUCTIONS.md.

## Development Commands

```bash
uv sync              # Install dependencies and project in dev mode
uv run wm --help     # Run the CLI
uv run wm status     # Example: git status across all subprojects
```

## Architecture

This is a `uv` project with a `src/` layout. The CLI entry point is `wm = workman.cli:cli` (defined in pyproject.toml).

- **cli.py** — Click group with subcommands: `status`, `build`, `push`, `prune`, `clean`. Accepts `-C` to override workspace root.
- **config.py** — Loads `.workman.yaml`, returns `WorkspaceConfig` / `ProjectConfig` dataclasses. Provides `get_docker_projects()` and `get_effective_latest_tag()` helpers.
- **git.py** — `show_status()` scans subdirectories for `.git/`, runs `git status --short`.
- **docker.py** — `build_images()`, `push_images()`, `prune_images()`. Tagging uses `YYYYMMDD-N` pattern; N is determined by checking local tags (and registry tags via skopeo if available).
- **cleanup.py** — `clean_workspace()` removes `dist/`, `build/`, `__pycache__/`, `*.egg-info/` recursively.

## Key Concepts

- **Docker image tagging**: Pattern `YYYYMMDD-N` where N starts at 1 per day, determined by existing tags on system or remote registry. A configurable "latest" tag (global default with per-project override) is also applied.
- **Registry detection**: An image is considered registry-hosted if the portion before the first `/` contains a `.` or `:`.
