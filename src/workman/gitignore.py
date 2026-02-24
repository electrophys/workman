from __future__ import annotations

from pathlib import Path

import click

MARKER_START = "# --- workman managed (do not edit) ---"
MARKER_END = "# --- end workman managed ---"


def update_gitignore(workspace_root: Path, project_names: list[str]) -> None:
    """Create or update .gitignore with a managed block listing project directories."""
    gitignore_path = workspace_root / ".gitignore"

    # Read existing content
    if gitignore_path.exists():
        existing = gitignore_path.read_text()
    else:
        existing = ""

    # Build the managed block
    managed_lines = [MARKER_START]
    for name in sorted(project_names):
        managed_lines.append(f"{name}/")
    managed_lines.append(MARKER_END)
    managed_block = "\n".join(managed_lines)

    # Replace existing managed block or append
    if MARKER_START in existing and MARKER_END in existing:
        before = existing[: existing.index(MARKER_START)]
        after = existing[existing.index(MARKER_END) + len(MARKER_END) :]
        new_content = before + managed_block + after
    else:
        # Append, ensuring a blank line separator
        if existing and not existing.endswith("\n"):
            existing += "\n"
        if existing and not existing.endswith("\n\n"):
            existing += "\n"
        new_content = existing + managed_block + "\n"

    gitignore_path.write_text(new_content)

    click.echo(f"Updated .gitignore with {len(project_names)} project(s).")
