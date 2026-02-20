from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


DEFAULT_LATEST_TAG = "latest"
CONFIG_FILENAME = ".workman.yaml"


@dataclass
class ProjectConfig:
    name: str
    path: Path
    image: str | None = None
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
        projects[name] = ProjectConfig(
            name=name,
            path=root / name,
            image=proj_raw.get("image"),
            latest_tag=proj_raw.get("latest_tag"),
        )

    return WorkspaceConfig(root=root, latest_tag=latest_tag, projects=projects)


def get_effective_latest_tag(ws: WorkspaceConfig, project: ProjectConfig) -> str:
    """Return the latest tag for a project, falling back to the workspace default."""
    return project.latest_tag or ws.latest_tag


def get_docker_projects(ws: WorkspaceConfig, names: tuple[str, ...] | None = None) -> list[ProjectConfig]:
    """Return docker-enabled projects, optionally filtered by name."""
    candidates = ws.projects.values() if not names else [
        ws.projects[n] for n in names if n in ws.projects
    ]
    result = [p for p in candidates if p.image]

    if names:
        missing = set(names) - {p.name for p in result}
        if missing:
            raise ValueError(
                f"Projects not found or have no image configured: {', '.join(sorted(missing))}"
            )

    return result
