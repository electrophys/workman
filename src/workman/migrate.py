from __future__ import annotations

import ast
import configparser
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import click
import tomli_w


LEGACY_FILES = ["setup.py", "setup.cfg", "requirements.txt"]

# Priority order: highest first
PRIORITY = ["pyproject.toml", "setup.cfg", "setup.py", "requirements.txt"]


@dataclass
class ProjectMetadata:
    """Aggregated metadata extracted from legacy config files."""

    name: str | None = None
    version: str | None = None
    description: str | None = None
    requires_python: str | None = None
    dependencies: list[str] = field(default_factory=list)
    optional_dependencies: dict[str, list[str]] = field(default_factory=dict)
    entry_points: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class MigrationResult:
    """Result of migrating a single project."""

    project_name: str
    sources_found: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_removed: list[str] = field(default_factory=list)
    skipped: bool = False


# ---------------------------------------------------------------------------
# AST helpers for setup.py parsing
# ---------------------------------------------------------------------------


def _find_setup_call(tree: ast.Module) -> ast.Call | None:
    """Find the setup() or setuptools.setup() call in the AST."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "setup":
            return node
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "setup"
            and isinstance(func.value, ast.Name)
        ):
            return node
    return None


def _ast_to_str(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _ast_to_str_list(node: ast.expr) -> list[str] | None:
    if isinstance(node, (ast.List, ast.Tuple)):
        result = []
        for elt in node.elts:
            s = _ast_to_str(elt)
            if s is None:
                return None
            result.append(s)
        return result
    return None


def _ast_to_dict_of_str_lists(node: ast.expr) -> dict[str, list[str]] | None:
    if not isinstance(node, ast.Dict):
        return None
    result: dict[str, list[str]] = {}
    for key, value in zip(node.keys, node.values):
        if key is None:
            return None  # **unpacking
        k = _ast_to_str(key)
        v = _ast_to_str_list(value)
        if k is None or v is None:
            return None
        result[k] = v
    return result


# ---------------------------------------------------------------------------
# Parsing functions
# ---------------------------------------------------------------------------


def parse_setup_py(path: Path) -> ProjectMetadata:
    """AST-parse a setup.py to extract setup() keyword arguments."""
    meta = ProjectMetadata(sources=["setup.py"])

    try:
        source = path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as e:
        meta.warnings.append(f"setup.py: could not parse ({e})")
        return meta

    call = _find_setup_call(tree)
    if call is None:
        meta.warnings.append("setup.py: no setup() call found")
        return meta

    for kw in call.keywords:
        if kw.arg is None:
            continue  # **kwargs

        if kw.arg == "name":
            val = _ast_to_str(kw.value)
            if val is not None:
                meta.name = val
            else:
                meta.warnings.append("setup.py: 'name' is dynamic, skipped")

        elif kw.arg == "version":
            val = _ast_to_str(kw.value)
            if val is not None:
                meta.version = val
            else:
                meta.warnings.append("setup.py: 'version' is dynamic, skipped")

        elif kw.arg == "description":
            val = _ast_to_str(kw.value)
            if val is not None:
                meta.description = val

        elif kw.arg == "python_requires":
            val = _ast_to_str(kw.value)
            if val is not None:
                meta.requires_python = val

        elif kw.arg == "install_requires":
            val = _ast_to_str_list(kw.value)
            if val is not None:
                meta.dependencies = val
            else:
                meta.warnings.append(
                    "setup.py: 'install_requires' is dynamic, skipped"
                )

        elif kw.arg == "extras_require":
            val = _ast_to_dict_of_str_lists(kw.value)
            if val is not None:
                meta.optional_dependencies = val

        elif kw.arg == "entry_points":
            d = _ast_to_dict_of_str_lists(kw.value)
            if d and "console_scripts" in d:
                for entry in d["console_scripts"]:
                    if "=" in entry:
                        name, _, target = entry.partition("=")
                        meta.entry_points[name.strip()] = target.strip()

    return meta


def parse_setup_cfg(path: Path) -> ProjectMetadata:
    """Parse a setup.cfg file using configparser."""
    meta = ProjectMetadata(sources=["setup.cfg"])

    cfg = configparser.ConfigParser()
    try:
        cfg.read(path, encoding="utf-8")
    except Exception as e:
        meta.warnings.append(f"setup.cfg: could not parse ({e})")
        return meta

    # [metadata]
    if cfg.has_section("metadata"):
        meta.name = cfg.get("metadata", "name", fallback=None)
        meta.version = cfg.get("metadata", "version", fallback=None)
        meta.description = cfg.get("metadata", "description", fallback=None)

    # [options]
    if cfg.has_section("options"):
        meta.requires_python = cfg.get("options", "python_requires", fallback=None)

        raw = cfg.get("options", "install_requires", fallback=None)
        if raw:
            meta.dependencies = [
                line.strip()
                for line in raw.strip().splitlines()
                if line.strip()
            ]

    # [options.extras_require]
    if cfg.has_section("options.extras_require"):
        for key in cfg.options("options.extras_require"):
            raw = cfg.get("options.extras_require", key)
            deps = [line.strip() for line in raw.strip().splitlines() if line.strip()]
            if deps:
                meta.optional_dependencies[key] = deps

    # [options.entry_points]
    if cfg.has_section("options.entry_points"):
        raw = cfg.get("options.entry_points", "console_scripts", fallback=None)
        if raw:
            for line in raw.strip().splitlines():
                line = line.strip()
                if line and "=" in line:
                    name, _, target = line.partition("=")
                    meta.entry_points[name.strip()] = target.strip()

    return meta


def parse_requirements_txt(
    path: Path, *, _visited: set[Path] | None = None,
) -> ProjectMetadata:
    """Parse a requirements.txt file into dependency list."""
    meta = ProjectMetadata(sources=["requirements.txt"])

    if _visited is None:
        _visited = set()

    resolved = path.resolve()
    if resolved in _visited:
        return meta
    _visited.add(resolved)

    try:
        lines = path.read_text().splitlines()
    except Exception as e:
        meta.warnings.append(f"requirements.txt: could not read ({e})")
        return meta

    for raw_line in lines:
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if line.startswith(("-r", "--requirement")):
            parts = line.split(None, 1)
            if len(parts) == 2:
                inc_path = path.parent / parts[1]
                sub = parse_requirements_txt(inc_path, _visited=_visited)
                meta.dependencies.extend(sub.dependencies)
                meta.warnings.extend(sub.warnings)
            continue

        if line.startswith(("-e", "--editable")):
            meta.warnings.append(f"requirements.txt: editable dep skipped: {line}")
            continue

        if line.startswith(("-i", "--index-url", "--extra-index-url", "--find-links",
                            "--no-binary", "--only-binary", "--trusted-host",
                            "-f", "--pre", "--no-deps")):
            continue

        # Treat as a PEP 508 dependency string
        meta.dependencies.append(line)

    return meta


def parse_existing_pyproject(path: Path) -> ProjectMetadata:
    """Read an existing pyproject.toml and extract [project] fields."""
    meta = ProjectMetadata(sources=["pyproject.toml"])

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        meta.warnings.append(f"pyproject.toml: could not parse ({e})")
        return meta

    project = data.get("project", {})
    meta.name = project.get("name")
    meta.version = project.get("version")
    meta.description = project.get("description")
    meta.requires_python = project.get("requires-python")
    meta.dependencies = project.get("dependencies", [])

    for group, deps in project.get("optional-dependencies", {}).items():
        meta.optional_dependencies[group] = deps

    for name, target in project.get("scripts", {}).items():
        meta.entry_points[name] = target

    return meta


# ---------------------------------------------------------------------------
# Merge and generate
# ---------------------------------------------------------------------------


def merge_metadata(sources: list[ProjectMetadata]) -> ProjectMetadata:
    """Merge metadata from multiple sources by priority order.

    Sources should already be ordered by priority (highest first).
    Scalars: first non-None wins. Dependencies: highest-priority non-empty wins.
    """
    merged = ProjectMetadata()

    for src in sources:
        merged.sources.extend(src.sources)
        merged.warnings.extend(src.warnings)

    for src in sources:
        if merged.name is None and src.name is not None:
            merged.name = src.name
        if merged.version is None and src.version is not None:
            merged.version = src.version
        if merged.description is None and src.description is not None:
            merged.description = src.description
        if merged.requires_python is None and src.requires_python is not None:
            merged.requires_python = src.requires_python

    # Dependencies: highest-priority non-empty list wins
    for src in sources:
        if src.dependencies:
            merged.dependencies = src.dependencies
            break

    # Optional deps: merge by group, higher priority wins per group
    for src in reversed(sources):  # lowest priority first so higher overwrites
        for group, deps in src.optional_dependencies.items():
            merged.optional_dependencies[group] = deps

    # Entry points: merge, higher priority wins per name
    for src in reversed(sources):
        for name, target in src.entry_points.items():
            merged.entry_points[name] = target

    return merged


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Merge overlay into base; base values take precedence."""
    result = dict(base)
    for key, value in overlay.items():
        if key not in result:
            result[key] = value
        elif isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
    return result


def build_pyproject_dict(metadata: ProjectMetadata, project_dir_name: str) -> dict:
    """Build a pyproject.toml dict from metadata with sensible defaults."""
    project: dict = {
        "name": metadata.name or project_dir_name,
        "version": metadata.version or "0.1.0",
        "requires-python": metadata.requires_python or ">=3.10",
    }

    if metadata.description:
        project["description"] = metadata.description

    if metadata.dependencies:
        project["dependencies"] = metadata.dependencies

    if metadata.optional_dependencies:
        project["optional-dependencies"] = metadata.optional_dependencies

    if metadata.entry_points:
        project["scripts"] = metadata.entry_points

    return {
        "build-system": {
            "requires": ["hatchling"],
            "build-backend": "hatchling.build",
        },
        "project": project,
    }


def write_pyproject(project_dir: Path, data: dict) -> None:
    """Write pyproject.toml, merging with existing content if present."""
    pyproject = project_dir / "pyproject.toml"

    if pyproject.exists():
        with open(pyproject, "rb") as f:
            existing = tomllib.load(f)
        merged = _deep_merge(existing, data)
    else:
        merged = data

    pyproject.write_bytes(tomli_w.dumps(merged).encode())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def migrate_project(project_dir: Path, *, clean: bool = False) -> MigrationResult:
    """Migrate a single project from legacy config to pyproject.toml."""
    result = MigrationResult(project_name=project_dir.name)

    # Detect legacy files
    legacy_found: dict[str, Path] = {}
    for name in LEGACY_FILES:
        p = project_dir / name
        if p.exists():
            legacy_found[name] = p

    has_pyproject = (project_dir / "pyproject.toml").exists()

    if not legacy_found and not has_pyproject:
        result.skipped = True
        return result

    if not legacy_found and has_pyproject:
        result.skipped = True
        return result

    result.sources_found = list(legacy_found.keys())

    # Parse each source in priority order
    parsed: list[ProjectMetadata] = []

    if has_pyproject:
        parsed.append(parse_existing_pyproject(project_dir / "pyproject.toml"))

    for source_name in ["setup.cfg", "setup.py", "requirements.txt"]:
        if source_name in legacy_found:
            if source_name == "setup.py":
                parsed.append(parse_setup_py(legacy_found[source_name]))
            elif source_name == "setup.cfg":
                parsed.append(parse_setup_cfg(legacy_found[source_name]))
            elif source_name == "requirements.txt":
                parsed.append(parse_requirements_txt(legacy_found[source_name]))

    # Merge and generate
    metadata = merge_metadata(parsed)
    result.warnings = metadata.warnings

    pyproject_data = build_pyproject_dict(metadata, project_dir.name)
    write_pyproject(project_dir, pyproject_data)

    # Cleanup
    if clean:
        for name, path in legacy_found.items():
            path.unlink()
            result.files_removed.append(name)

    return result


def migrate_projects(
    workspace_root: Path,
    project_names: tuple[str, ...] | None,
    *,
    clean: bool = False,
) -> None:
    """Migrate legacy Python projects to pyproject.toml."""
    subdirs = sorted(
        p for p in workspace_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
    if project_names is not None:
        subdirs = [d for d in subdirs if d.name in project_names]

    migrated = 0
    skipped = 0

    for subdir in subdirs:
        result = migrate_project(subdir, clean=clean)

        if result.skipped:
            skipped += 1
            continue

        migrated += 1
        click.echo(f"\n{click.style(result.project_name, bold=True)}:")
        click.echo(f"  found: {', '.join(result.sources_found)}")

        if result.warnings:
            for w in result.warnings:
                click.echo(f"  {click.style('warning', fg='yellow')}: {w}")

        click.echo(f"  wrote pyproject.toml")

        if result.files_removed:
            click.echo(f"  removed: {', '.join(result.files_removed)}")

    click.echo(f"\nMigrated {migrated} project(s). {skipped} skipped.")
