from __future__ import annotations

import subprocess
from pathlib import Path

import click
import yaml

from workman.config import CONFIG_FILENAME
from workman.gitignore import update_gitignore


def _get_subdirs(workspace_root: Path) -> list[Path]:
    """Return immediate non-hidden subdirectories."""
    return sorted(
        p for p in workspace_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def _find_dockerfiles(path: Path) -> list[str]:
    """Return Dockerfile names found in a directory (Dockerfile, Dockerfile.*)."""
    results = []
    for f in sorted(path.iterdir()):
        if f.is_file() and (f.name == "Dockerfile" or f.name.startswith("Dockerfile.")):
            results.append(f.name)
    return results


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
        basename = repo.rsplit("/", 1)[-1]
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

    local_images = _get_local_images()

    projects: dict[str, dict] = {}

    for subdir in subdirs:
        name = subdir.name
        dockerfiles = _find_dockerfiles(subdir)
        matched_image = local_images.get(name)

        if not dockerfiles and not matched_image:
            click.echo(f"  {click.style(name, bold=True)}: skipped (no Dockerfile or matching image)")
            continue

        images: list[dict[str, str]] = []

        if len(dockerfiles) <= 1:
            # Single or no Dockerfile — one image entry
            image_name = matched_image or name
            entry: dict[str, str] = {"name": image_name}
            if dockerfiles and dockerfiles[0] != "Dockerfile":
                entry["dockerfile"] = dockerfiles[0]
            images.append(entry)
        else:
            # Multiple Dockerfiles — one image per Dockerfile
            for df in dockerfiles:
                suffix = df.removeprefix("Dockerfile").lstrip(".")
                image_name = f"{matched_image or name}-{suffix}" if suffix else (matched_image or name)
                entry = {"name": image_name, "dockerfile": df}
                images.append(entry)

        projects[name] = {"images": images}

        desc = ", ".join(img["name"] for img in images)
        click.echo(f"  {click.style(name, bold=True)}: {desc}")

    config: dict = {"latest_tag": "latest"}
    if projects:
        config["projects"] = projects

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    click.echo(f"\nWrote {CONFIG_FILENAME} with {len(projects)} project(s).")

    # Update .gitignore with all subdirectory names
    all_subdir_names = [d.name for d in subdirs]
    update_gitignore(workspace_root, all_subdir_names)
