from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


DEFAULT_LATEST_TAG = "latest"
CONFIG_FILENAME = ".workman.yaml"


@dataclass
class ImageConfig:
    name: str
    dockerfile: str | None = None  # relative to build context
    context: Path | None = None  # absolute; resolved from workspace root at load time


@dataclass
class ProjectConfig:
    name: str
    path: Path
    images: list[ImageConfig] = field(default_factory=list)
    latest_tag: str | None = None  # per-project override


@dataclass
class WorkspaceConfig:
    root: Path
    latest_tag: str = DEFAULT_LATEST_TAG
    projects: dict[str, ProjectConfig] = field(default_factory=dict)


def load_config(workspace_root: Path | None = None) -> WorkspaceConfig:
    """Load .workman.yaml from the workspace root directory."""
    root = (workspace_root or Path.cwd()).resolve()
    config_path = root / CONFIG_FILENAME

    if not config_path.exists():
        raise FileNotFoundError(
            f"No {CONFIG_FILENAME} found in {root}. "
            "Are you in a workman workspace?"
        )

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    latest_tag = raw.get("latest_tag", DEFAULT_LATEST_TAG)

    projects: dict[str, ProjectConfig] = {}
    for name, proj_raw in (raw.get("projects") or {}).items():
        proj_raw = proj_raw or {}

        images: list[ImageConfig] = []
        for img_raw in proj_raw.get("images") or []:
            ctx_raw = img_raw.get("context")
            images.append(ImageConfig(
                name=img_raw["name"],
                dockerfile=img_raw.get("dockerfile"),
                context=root / ctx_raw if ctx_raw else None,
            ))

        projects[name] = ProjectConfig(
            name=name,
            path=root / name,
            images=images,
            latest_tag=proj_raw.get("latest_tag"),
        )

    return WorkspaceConfig(root=root, latest_tag=latest_tag, projects=projects)


def get_build_context(project: ProjectConfig, image: ImageConfig) -> Path:
    """Return the docker build context directory, defaulting to the project folder."""
    return image.context or project.path


def get_effective_latest_tag(ws: WorkspaceConfig, project: ProjectConfig) -> str:
    """Return the latest tag for a project, falling back to the workspace default."""
    return project.latest_tag or ws.latest_tag


def get_docker_projects(ws: WorkspaceConfig, names: tuple[str, ...] | None = None) -> list[ProjectConfig]:
    """Return docker-enabled projects (those with at least one image), optionally filtered by name."""
    candidates = ws.projects.values() if not names else [
        ws.projects[n] for n in names if n in ws.projects
    ]
    result = [p for p in candidates if p.images]

    if names:
        missing = set(names) - {p.name for p in result}
        if missing:
            raise ValueError(
                f"Projects not found or have no images configured: {', '.join(sorted(missing))}"
            )

    return result
