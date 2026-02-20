from __future__ import annotations

import shutil
from pathlib import Path

import click

CLEANUP_DIRS = {"dist", "build", "__pycache__"}
CLEANUP_SUFFIXES = {".egg-info"}


def clean_workspace(workspace_root: Path) -> None:
    """Remove Python build artifacts from all subdirectories."""
    removed = 0

    for item in sorted(workspace_root.rglob("*")):
        if not item.is_dir():
            continue

        should_remove = (
            item.name in CLEANUP_DIRS
            or any(item.name.endswith(s) for s in CLEANUP_SUFFIXES)
        )

        if should_remove:
            rel = item.relative_to(workspace_root)
            click.echo(f"  removing {rel}")
            shutil.rmtree(item)
            removed += 1

    if removed:
        click.echo(f"Removed {removed} directories.")
    else:
        click.echo("Nothing to clean.")
