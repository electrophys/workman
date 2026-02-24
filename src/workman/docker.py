from __future__ import annotations

import re
import subprocess
from datetime import date

import click

from workman.config import (
    ImageConfig,
    ProjectConfig,
    WorkspaceConfig,
    get_build_context,
    get_docker_projects,
    get_effective_latest_tag,
)

DATE_TAG_PATTERN = re.compile(r"^(\d{8})-(\d+)$")


def _has_registry(image_name: str) -> bool:
    """Check if an image name includes a registry (has a dot before the first slash)."""
    if "/" not in image_name:
        return False
    prefix = image_name.split("/")[0]
    return "." in prefix or ":" in prefix


def _get_local_tags(image_name: str) -> list[str]:
    """List local tags for a given image name."""
    result = subprocess.run(
        ["docker", "image", "ls", "--format", "{{.Tag}}", image_name],
        capture_output=True,
        text=True,
    )
    return [t.strip() for t in result.stdout.strip().splitlines() if t.strip()]


def _get_registry_tags(image_name: str) -> list[str]:
    """Try to list tags from the registry using skopeo."""
    try:
        result = subprocess.run(
            ["skopeo", "list-tags", f"docker://{image_name}"],
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


def _next_tag(image_name: str) -> str:
    """Determine the next YYYYMMDD-N tag for an image."""
    today = date.today().strftime("%Y%m%d")

    tags = _get_local_tags(image_name)
    if _has_registry(image_name):
        tags.extend(_get_registry_tags(image_name))

    n = _max_n_for_today(tags, today) + 1
    return f"{today}-{n}"


def build_images(ws: WorkspaceConfig, names: tuple[str, ...]) -> None:
    """Build docker images for selected (or all) projects."""
    projects = get_docker_projects(ws, names or None)

    if not projects:
        click.echo("No docker-enabled projects found.")
        return

    for proj in projects:
        latest = get_effective_latest_tag(ws, proj)

        for img in proj.images:
            tag = _next_tag(img.name)
            context = get_build_context(proj, img)

            click.echo(
                f"{click.style(proj.name, bold=True)}: "
                f"building {img.name}:{tag} in {context}"
            )

            cmd = [
                "docker", "build",
                "-t", f"{img.name}:{tag}",
                "-t", f"{img.name}:{latest}",
            ]
            if img.dockerfile:
                cmd.extend(["-f", str(context / img.dockerfile)])
            cmd.append(str(context))

            result = subprocess.run(cmd)
            if result.returncode != 0:
                raise click.ClickException(
                    f"Docker build failed for {proj.name} ({img.name})"
                )

            click.echo(
                f"  tagged {img.name}:{tag} and {img.name}:{latest}"
            )


def push_images(ws: WorkspaceConfig, names: tuple[str, ...]) -> None:
    """Push images that have a registry in the name."""
    projects = get_docker_projects(ws, names or None)

    found_any = False
    for proj in projects:
        latest = get_effective_latest_tag(ws, proj)

        for img in proj.images:
            if not _has_registry(img.name):
                continue
            found_any = True
            tags = _get_local_tags(img.name)

            date_tags = []
            for t in tags:
                m = DATE_TAG_PATTERN.match(t)
                if m:
                    date_tags.append((t, m.group(1), int(m.group(2))))

            if not date_tags:
                click.echo(
                    f"{click.style(proj.name, bold=True)} ({img.name}): "
                    f"no date-tagged images to push"
                )
                continue

            date_tags.sort(key=lambda x: (x[1], x[2]), reverse=True)
            most_recent = date_tags[0][0]

            for push_tag in (most_recent, latest):
                ref = f"{img.name}:{push_tag}"
                click.echo(f"{click.style(proj.name, bold=True)}: pushing {ref}")
                result = subprocess.run(["docker", "push", ref])
                if result.returncode != 0:
                    raise click.ClickException(f"Push failed for {ref}")

    if not found_any:
        click.echo("No projects with registry images found.")


def prune_images(ws: WorkspaceConfig, names: tuple[str, ...] | None = None) -> None:
    """Remove all images except the most recent for each project."""
    projects = get_docker_projects(ws, names)

    if not projects:
        click.echo("No docker-enabled projects found.")
        return

    for proj in projects:
        latest = get_effective_latest_tag(ws, proj)

        for img in proj.images:
            tags = _get_local_tags(img.name)

            date_tags = []
            for t in tags:
                m = DATE_TAG_PATTERN.match(t)
                if m:
                    date_tags.append((t, m.group(1), int(m.group(2))))

            date_tags.sort(key=lambda x: (x[1], x[2]), reverse=True)

            keep = {latest}
            if date_tags:
                keep.add(date_tags[0][0])

            to_remove = [t for t in tags if t not in keep and t != "<none>"]

            if not to_remove:
                click.echo(
                    f"{click.style(proj.name, bold=True)} ({img.name}): nothing to prune"
                )
                continue

            for t in to_remove:
                ref = f"{img.name}:{t}"
                click.echo(f"{click.style(proj.name, bold=True)}: removing {ref}")
                subprocess.run(
                    ["docker", "rmi", ref],
                    capture_output=True,
                )
