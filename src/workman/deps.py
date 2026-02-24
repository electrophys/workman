from __future__ import annotations

import re
import tomllib
from pathlib import Path

import click
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version


def _parse_deps(dep_list: list[str]) -> dict[str, str]:
    """Parse a list of PEP 508 dependency strings into {name: specifier_string}."""
    result: dict[str, str] = {}
    for dep_str in dep_list:
        try:
            req = Requirement(dep_str)
        except Exception:
            continue
        name = req.name.lower()
        spec = str(req.specifier)
        result[name] = spec
    return result


def scan_dependencies(
    workspace_root: Path,
    project_names: tuple[str, ...] | None = None,
) -> dict[str, dict[str, str]]:
    """Scan pyproject.toml files and return {package: {project: specifier}}.

    Scans [project].dependencies, [dependency-groups], and
    [project.optional-dependencies].
    """
    subdirs = sorted(
        p for p in workspace_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
    if project_names is not None:
        subdirs = [d for d in subdirs if d.name in project_names]

    # {package_name: {project_name: specifier_string}}
    packages: dict[str, dict[str, str]] = {}

    for subdir in subdirs:
        pyproject = subdir / "pyproject.toml"
        if not pyproject.exists():
            continue

        with open(pyproject, "rb") as f:
            try:
                data = tomllib.load(f)
            except Exception:
                continue

        all_deps: dict[str, str] = {}

        # Main dependencies
        main = data.get("project", {}).get("dependencies", [])
        all_deps.update(_parse_deps(main))

        # Optional dependencies
        for group_deps in data.get("project", {}).get("optional-dependencies", {}).values():
            all_deps.update(_parse_deps(group_deps))

        # Dependency groups (PEP 735 / uv)
        for group_deps in data.get("dependency-groups", {}).values():
            if isinstance(group_deps, list):
                # Filter to plain strings (skip include-group dicts)
                all_deps.update(_parse_deps(
                    [d for d in group_deps if isinstance(d, str)]
                ))

        for pkg_name, spec_str in all_deps.items():
            packages.setdefault(pkg_name, {})[subdir.name] = spec_str

    return packages


def find_mismatches(packages: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Return only packages where specifiers differ across projects."""
    return {
        pkg: projects
        for pkg, projects in packages.items()
        if len(projects) > 1 and len(set(projects.values())) > 1
    }


def _extract_min_version(spec_str: str) -> Version | None:
    """Extract the minimum version from a >= specifier."""
    spec = SpecifierSet(spec_str)
    best: Version | None = None
    for s in spec:
        if s.operator == ">=":
            v = Version(s.version)
            if best is None or v > best:
                best = v
    return best


def _is_simple_gte(spec_str: str) -> bool:
    """Check if a specifier is a simple >=X.Y.Z (possibly empty)."""
    if not spec_str:
        return True
    spec = SpecifierSet(spec_str)
    return all(s.operator == ">=" for s in spec)


def highest_minimum(specifiers: dict[str, str]) -> str | None:
    """Find the highest >=X.Y.Z across a set of specifier strings.

    Returns None if any specifier is not a simple >= (has ==, <, ~= etc).
    """
    if not all(_is_simple_gte(s) for s in specifiers.values()):
        return None

    best: Version | None = None
    for spec_str in specifiers.values():
        v = _extract_min_version(spec_str)
        if v is not None and (best is None or v > best):
            best = v

    return f">={best}" if best else None


def _update_dep_line(content: str, package_name: str, new_spec: str) -> str:
    """Replace a dependency's version specifier in pyproject.toml text."""
    # Match the package name (case-insensitive) followed by any specifier
    # in a dependencies list context
    pattern = re.compile(
        rf'(?i)((?:^|\s|["\'])({re.escape(package_name)}))\s*([><=!~][^\s"\'#,\]]*)?',
    )

    def replacer(m: re.Match) -> str:
        return f"{m.group(1)}{new_spec}"

    return pattern.sub(replacer, content)


def align_dependencies(
    workspace_root: Path,
    mismatches: dict[str, dict[str, str]],
) -> None:
    """Update pyproject.toml files to align dependency versions."""
    for pkg, projects in sorted(mismatches.items()):
        target = highest_minimum(projects)
        if target is None:
            click.echo(
                f"  {click.style(pkg, bold=True)}: "
                f"{click.style('skipped', fg='yellow')} (has exact pins or complex ranges)"
            )
            continue

        click.echo(f"  {click.style(pkg, bold=True)}: aligning to {target}")

        for proj_name, spec_str in projects.items():
            if spec_str == target:
                continue

            pyproject = workspace_root / proj_name / "pyproject.toml"
            content = pyproject.read_text()
            new_content = _update_dep_line(content, pkg, target)

            if new_content != content:
                pyproject.write_text(new_content)
                click.echo(f"    updated {proj_name}/pyproject.toml")


def show_report(mismatches: dict[str, dict[str, str]]) -> None:
    """Print a report of dependency version mismatches."""
    if not mismatches:
        click.echo("All dependency versions are aligned.")
        return

    click.echo(f"Found {len(mismatches)} package(s) with version mismatches:\n")

    for pkg in sorted(mismatches):
        projects = mismatches[pkg]
        click.echo(f"{click.style(pkg, bold=True)}:")
        max_name_len = max(len(n) for n in projects)
        for proj_name, spec_str in sorted(projects.items()):
            display_spec = spec_str or "(any)"
            click.echo(f"  {proj_name:<{max_name_len}}  {display_spec}")
        click.echo()
