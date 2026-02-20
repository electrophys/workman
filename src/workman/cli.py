from __future__ import annotations

from pathlib import Path

import click

from workman.config import load_config


@click.group()
@click.option(
    "-C",
    "workspace",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Workspace root directory (default: current directory).",
)
@click.pass_context
def cli(ctx: click.Context, workspace: Path | None) -> None:
    """Workman — manage a workspace of projects."""
    ctx.ensure_object(dict)
    ctx.obj["workspace"] = (workspace or Path.cwd()).resolve()


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show git status for all repositories in the workspace."""
    from workman.git import show_status

    show_status(ctx.obj["workspace"])


@cli.command()
@click.argument("projects", nargs=-1)
@click.pass_context
def build(ctx: click.Context, projects: tuple[str, ...]) -> None:
    """Build docker images for projects (all if none specified)."""
    ws = load_config(ctx.obj["workspace"])
    from workman.docker import build_images

    build_images(ws, projects)


@cli.command()
@click.argument("projects", nargs=-1)
@click.pass_context
def push(ctx: click.Context, projects: tuple[str, ...]) -> None:
    """Push docker images to their registries."""
    ws = load_config(ctx.obj["workspace"])
    from workman.docker import push_images

    push_images(ws, projects)


@cli.command()
@click.pass_context
def prune(ctx: click.Context) -> None:
    """Remove all docker images except the most recent for each project."""
    ws = load_config(ctx.obj["workspace"])
    from workman.docker import prune_images

    prune_images(ws)


@cli.command()
@click.pass_context
def clean(ctx: click.Context) -> None:
    """Remove Python build artifacts from all projects."""
    from workman.cleanup import clean_workspace

    clean_workspace(ctx.obj["workspace"])
