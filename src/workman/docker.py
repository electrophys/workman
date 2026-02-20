from __future__ import annotations

import re
import subprocess
from datetime import date

import click

from workman.config import (
    ProjectConfig,
    WorkspaceConfig,
    get_docker_projects,
    get_effective_latest_tag,
)

DATE_TAG_PATTERN = re.compile(r"^(\d{8})-(\d+)$")


def _has_registry(image: str) -> bool:
    """Check if an image name includes a registry (has a dot before the first slash)."""
    if "/" not in image:
        return False
    prefix = image.split("/")[0]
    return "." in prefix or ":" in prefix


def _get_local_tags(image: str) -> list[str]:
    """List local tags for a given image name."""
    result = subprocess.run(
        ["docker", "image", "ls", "--format", "{{.Tag}}", image],
        capture_output=True,
        text=True,
    )
    return [t.strip() for t in result.stdout.strip().splitlines() if t.strip()]


def _get_registry_tags(image: str) -> list[str]:
    """Try to list tags from the registry using docker manifest inspect or skopeo."""
    # Use skopeo if available, otherwise fall back to nothing
    try:
        result = subprocess.run(
            ["skopeo", "list-tags", f"docker://{image}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            return data.get("Tags", [])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []


def _max_n_for_today(tags: list[str], today: str) -> int:
    """Find the maximum N for today's date pattern in a list of tags."""
    max_n = 0
    for tag in tags:
        m = DATE_TAG_PATTERN.match(tag)
        if m and m.group(1) == today:
            max_n = max(max_n, int(m.group(2)))
    return max_n


def _next_tag(image: str) -> str:
    """Determine the next YYYYMMDD-N tag for an image."""
    today = date.today().strftime("%Y%m%d")

    tags = _get_local_tags(image)
    if _has_registry(image):
        tags.extend(_get_registry_tags(image))

    n = _max_n_for_today(tags, today) + 1
    return f"{today}-{n}"


def build_images(ws: WorkspaceConfig, names: tuple[str, ...]) -> None:
    """Build docker images for selected (or all) projects."""
    projects = get_docker_projects(ws, names or None)

    if not projects:
        click.echo("No docker-enabled projects found.")
        return

    for proj in projects:
        tag = _next_tag(proj.image)
        latest = get_effective_latest_tag(ws, proj)

        click.echo(
            f"{click.style(proj.name, bold=True)}: "
            f"building {proj.image}:{tag}"
        )

        cmd = [
            "docker", "build",
            "-t", f"{proj.image}:{tag}",
            "-t", f"{proj.image}:{latest}",
            str(proj.path),
        ]

        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise click.ClickException(
                f"Docker build failed for {proj.name}"
            )

        click.echo(
            f"  tagged {proj.image}:{tag} and {proj.image}:{latest}"
        )


def push_images(ws: WorkspaceConfig, names: tuple[str, ...]) -> None:
    """Push images that have a registry in the name."""
    projects = get_docker_projects(ws, names or None)
    pushable = [p for p in projects if _has_registry(p.image)]

    if not pushable:
        click.echo("No projects with registry images found.")
        return

    for proj in pushable:
        latest = get_effective_latest_tag(ws, proj)
        tags = _get_local_tags(proj.image)

        # Find the most recent date tag
        today_tags = []
        for t in tags:
            m = DATE_TAG_PATTERN.match(t)
            if m:
                today_tags.append((t, m.group(1), int(m.group(2))))

        if not today_tags:
            click.echo(
                f"{click.style(proj.name, bold=True)}: no date-tagged images to push"
            )
            continue

        # Sort by date desc then N desc, push the most recent
        today_tags.sort(key=lambda x: (x[1], x[2]), reverse=True)
        most_recent = today_tags[0][0]

        for push_tag in (most_recent, latest):
            ref = f"{proj.image}:{push_tag}"
            click.echo(f"{click.style(proj.name, bold=True)}: pushing {ref}")
            result = subprocess.run(["docker", "push", ref])
            if result.returncode != 0:
                raise click.ClickException(f"Push failed for {ref}")


def prune_images(ws: WorkspaceConfig) -> None:
    """Remove all images except the most recent for each project."""
    projects = get_docker_projects(ws)

    if not projects:
        click.echo("No docker-enabled projects found.")
        return

    for proj in projects:
        latest = get_effective_latest_tag(ws, proj)
        tags = _get_local_tags(proj.image)

        date_tags = []
        for t in tags:
            m = DATE_TAG_PATTERN.match(t)
            if m:
                date_tags.append((t, m.group(1), int(m.group(2))))

        # Sort by date desc then N desc
        date_tags.sort(key=lambda x: (x[1], x[2]), reverse=True)

        # Keep the most recent date tag and the latest tag; remove everything else
        keep = {latest}
        if date_tags:
            keep.add(date_tags[0][0])

        to_remove = [t for t in tags if t not in keep and t != "<none>"]

        if not to_remove:
            click.echo(f"{click.style(proj.name, bold=True)}: nothing to prune")
            continue

        for t in to_remove:
            ref = f"{proj.image}:{t}"
            click.echo(f"{click.style(proj.name, bold=True)}: removing {ref}")
            subprocess.run(
                ["docker", "rmi", ref],
                capture_output=True,
            )
