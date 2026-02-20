from __future__ import annotations

import subprocess
from pathlib import Path

import click
import yaml

from workman.config import CONFIG_FILENAME


def _get_subdirs(workspace_root: Path) -> list[Path]:
    """Return immediate non-hidden subdirectories."""
    return sorted(
        p for p in workspace_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def _has_dockerfile(path: Path) -> bool:
    return (path / "Dockerfile").exists()


def _get_local_images() -> dict[str, str]:
    """Return a map of image-name-fragment -> full repository name for local Docker images."""
    result = subprocess.run(
        ["docker", "image", "ls", "--format", "{{.Repository}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}

    images: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        repo = line.strip()
        if not repo or repo == "<none>":
            continue
        # Map the final path component to the full repo name.
        # e.g. "registry.example.com/org/myapp" -> "myapp" => full name
        basename = repo.rsplit("/", 1)[-1]
        # Keep the first (most specific) match if there are duplicates.
        if basename not in images:
            images[basename] = repo

    return images


def init_workspace(workspace_root: Path) -> None:
    """Scan the workspace and generate a .workman.yaml."""
    config_path = workspace_root / CONFIG_FILENAME

    if config_path.exists():
        raise click.ClickException(
            f"{CONFIG_FILENAME} already exists in {workspace_root}. "
            "Remove it first if you want to re-initialize."
        )

    subdirs = _get_subdirs(workspace_root)
    if not subdirs:
        raise click.ClickException("No subdirectories found in workspace.")

    # Fetch local Docker images for matching
    local_images = _get_local_images()

    projects: dict[str, dict[str, str]] = {}

    for subdir in subdirs:
        name = subdir.name
        has_docker = _has_dockerfile(subdir)
        matched_image = local_images.get(name)

        if has_docker or matched_image:
            entry: dict[str, str] = {}
            if matched_image:
                entry["image"] = matched_image
            elif has_docker:
                entry["image"] = name
            projects[name] = entry
            status_parts = []
            if has_docker:
                status_parts.append("Dockerfile")
            if matched_image:
                status_parts.append(f"image: {matched_image}")
            click.echo(
                f"  {click.style(name, bold=True)}: {', '.join(status_parts)}"
            )
        else:
            click.echo(f"  {click.style(name, bold=True)}: skipped (no Dockerfile or matching image)")

    config: dict = {"latest_tag": "latest"}
    if projects:
        config["projects"] = projects

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    click.echo(f"\nWrote {CONFIG_FILENAME} with {len(projects)} project(s).")
