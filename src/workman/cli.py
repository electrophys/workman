from __future__ import annotations

from pathlib import Path

import click

from workman.config import load_config, resolve_projects


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
def init(ctx: click.Context) -> None:
    """Scan the workspace and generate a .workman.yaml config file."""
    from workman.init import init_workspace

    init_workspace(ctx.obj["workspace"])


@cli.command()
@click.argument("projects", nargs=-1)
@click.pass_context
def status(ctx: click.Context, projects: tuple[str, ...]) -> None:
    """Show git status for repositories in the workspace.

    Optionally specify projects or @groups to filter. Use @all for everything.
    """
    from workman.git import show_status

    ws = load_config(ctx.obj["workspace"])
    names = resolve_projects(ws, projects)
    show_status(ctx.obj["workspace"], names)


@cli.command()
@click.argument("projects", nargs=-1)
@click.pass_context
def build(ctx: click.Context, projects: tuple[str, ...]) -> None:
    """Build docker images for projects (all if none specified).

    Specify projects or @groups. Use @all for everything.
    """
    ws = load_config(ctx.obj["workspace"])
    names = resolve_projects(ws, projects)
    from workman.docker import build_images

    build_images(ws, names)


@cli.command()
@click.argument("projects", nargs=-1)
@click.pass_context
def push(ctx: click.Context, projects: tuple[str, ...]) -> None:
    """Push docker images to their registries.

    Specify projects or @groups. Use @all for everything.
    """
    ws = load_config(ctx.obj["workspace"])
    names = resolve_projects(ws, projects)
    from workman.docker import push_images

    push_images(ws, names)


@cli.command()
@click.argument("projects", nargs=-1)
@click.pass_context
def prune(ctx: click.Context, projects: tuple[str, ...]) -> None:
    """Remove all docker images except the most recent for each project.

    Specify projects or @groups. Use @all for everything.
    """
    ws = load_config(ctx.obj["workspace"])
    names = resolve_projects(ws, projects)
    from workman.docker import prune_images

    prune_images(ws, names)


@cli.command()
@click.pass_context
def gitignore(ctx: click.Context) -> None:
    """Update .gitignore to exclude subproject folders from the workspace repo."""
    ws = load_config(ctx.obj["workspace"])
    from workman.gitignore import update_gitignore

    update_gitignore(ctx.obj["workspace"], list(ws.projects.keys()))


@cli.command()
@click.argument("projects", nargs=-1)
@click.pass_context
def clean(ctx: click.Context, projects: tuple[str, ...]) -> None:
    """Remove Python build artifacts from projects.

    Specify projects or @groups. Use @all for everything.
    """
    ws = load_config(ctx.obj["workspace"])
    names = resolve_projects(ws, projects)
    from workman.cleanup import clean_workspace

    clean_workspace(ctx.obj["workspace"], names)
