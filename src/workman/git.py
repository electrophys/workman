from __future__ import annotations

import subprocess
from pathlib import Path

import click


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def get_git_status(repo_path: Path) -> str:
    """Run git status --short and return the output."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--short"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def show_status(workspace_root: Path, project_names: tuple[str, ...] | None = None) -> None:
    """Print git status for the workspace repo (if any) and subproject repos."""

    # Workspace-level repo (always shown)
    if is_git_repo(workspace_root):
        status = get_git_status(workspace_root)
        header = click.style("workspace", bold=True, fg="cyan")
        if status:
            click.echo(f"{header}:")
            for line in status.splitlines():
                click.echo(f"  {line}")
        else:
            click.echo(f"{header}: {click.style('clean', fg='green')}")

    # Subproject repos
    subdirs = sorted(
        p for p in workspace_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )

    if project_names is not None:
        subdirs = [d for d in subdirs if d.name in project_names]

    repos = [d for d in subdirs if is_git_repo(d)]

    if not repos and not is_git_repo(workspace_root):
        click.echo("No git repositories found in workspace.")
        return

    for repo in repos:
        status = get_git_status(repo)
        header = click.style(repo.name, bold=True)
        if status:
            click.echo(f"{header}:")
            for line in status.splitlines():
                click.echo(f"  {line}")
        else:
            click.echo(f"{header}: {click.style('clean', fg='green')}")
