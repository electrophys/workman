import tomllib
from pathlib import Path
from textwrap import dedent

import pytest

from workman.migrate import (
    MigrationResult,
    ProjectMetadata,
    _deep_merge,
    build_pyproject_dict,
    merge_metadata,
    migrate_project,
    migrate_projects,
    parse_existing_pyproject,
    parse_requirements_txt,
    parse_setup_cfg,
    parse_setup_py,
    write_pyproject,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.write_text(dedent(content))


def _make_setup_py(project_dir: Path, **kwargs) -> None:
    lines = []
    for key, val in kwargs.items():
        lines.append(f"    {key}={val!r},")
    body = "\n".join(lines)
    (project_dir / "setup.py").write_text(
        f"from setuptools import setup\n\nsetup(\n{body}\n)\n"
    )


def _make_setup_cfg(project_dir: Path, sections: dict[str, dict[str, str]]) -> None:
    lines = []
    for section, options in sections.items():
        lines.append(f"[{section}]")
        for key, value in options.items():
            lines.append(f"{key} = {value}")
        lines.append("")
    (project_dir / "setup.cfg").write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# parse_setup_py
# ---------------------------------------------------------------------------


class TestParseSetupPy:
    def test_basic_fields(self, tmp_path):
        _make_setup_py(
            tmp_path, name="myapp", version="1.0.0", description="A cool app",
        )
        meta = parse_setup_py(tmp_path / "setup.py")
        assert meta.name == "myapp"
        assert meta.version == "1.0.0"
        assert meta.description == "A cool app"

    def test_install_requires(self, tmp_path):
        _make_setup_py(
            tmp_path, name="myapp", install_requires=["click>=8.0", "requests>=2.28"],
        )
        meta = parse_setup_py(tmp_path / "setup.py")
        assert meta.dependencies == ["click>=8.0", "requests>=2.28"]

    def test_python_requires(self, tmp_path):
        _make_setup_py(tmp_path, name="myapp", python_requires=">=3.10")
        meta = parse_setup_py(tmp_path / "setup.py")
        assert meta.requires_python == ">=3.10"

    def test_extras_require(self, tmp_path):
        _make_setup_py(
            tmp_path, name="myapp",
            extras_require={"dev": ["pytest>=7.0"], "docs": ["sphinx"]},
        )
        meta = parse_setup_py(tmp_path / "setup.py")
        assert meta.optional_dependencies == {
            "dev": ["pytest>=7.0"],
            "docs": ["sphinx"],
        }

    def test_console_scripts(self, tmp_path):
        _make_setup_py(
            tmp_path, name="myapp",
            entry_points={"console_scripts": ["myapp = myapp.cli:main"]},
        )
        meta = parse_setup_py(tmp_path / "setup.py")
        assert meta.entry_points == {"myapp": "myapp.cli:main"}

    def test_dynamic_version_warning(self, tmp_path):
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\n"
            "import myapp\n"
            "setup(name='myapp', version=myapp.__version__)\n"
        )
        meta = parse_setup_py(tmp_path / "setup.py")
        assert meta.name == "myapp"
        assert meta.version is None
        assert any("version" in w and "dynamic" in w for w in meta.warnings)

    def test_no_setup_call(self, tmp_path):
        (tmp_path / "setup.py").write_text("print('hello')\n")
        meta = parse_setup_py(tmp_path / "setup.py")
        assert any("no setup() call" in w for w in meta.warnings)

    def test_syntax_error(self, tmp_path):
        (tmp_path / "setup.py").write_text("def broken(\n")
        meta = parse_setup_py(tmp_path / "setup.py")
        assert any("could not parse" in w for w in meta.warnings)

    def test_setuptools_dot_setup(self, tmp_path):
        (tmp_path / "setup.py").write_text(
            "import setuptools\n"
            "setuptools.setup(name='myapp', version='2.0')\n"
        )
        meta = parse_setup_py(tmp_path / "setup.py")
        assert meta.name == "myapp"
        assert meta.version == "2.0"


# ---------------------------------------------------------------------------
# parse_setup_cfg
# ---------------------------------------------------------------------------


class TestParseSetupCfg:
    def test_metadata_section(self, tmp_path):
        _make_setup_cfg(tmp_path, {
            "metadata": {
                "name": "myapp",
                "version": "1.0.0",
                "description": "A cool app",
            },
        })
        meta = parse_setup_cfg(tmp_path / "setup.cfg")
        assert meta.name == "myapp"
        assert meta.version == "1.0.0"
        assert meta.description == "A cool app"

    def test_install_requires(self, tmp_path):
        _make_setup_cfg(tmp_path, {
            "metadata": {"name": "myapp"},
            "options": {"install_requires": "\n    click>=8.0\n    requests>=2.28"},
        })
        meta = parse_setup_cfg(tmp_path / "setup.cfg")
        assert meta.dependencies == ["click>=8.0", "requests>=2.28"]

    def test_python_requires(self, tmp_path):
        _make_setup_cfg(tmp_path, {
            "metadata": {"name": "myapp"},
            "options": {"python_requires": ">=3.10"},
        })
        meta = parse_setup_cfg(tmp_path / "setup.cfg")
        assert meta.requires_python == ">=3.10"

    def test_extras_require(self, tmp_path):
        _make_setup_cfg(tmp_path, {
            "metadata": {"name": "myapp"},
            "options.extras_require": {"dev": "\n    pytest>=7.0\n    ruff"},
        })
        meta = parse_setup_cfg(tmp_path / "setup.cfg")
        assert meta.optional_dependencies == {"dev": ["pytest>=7.0", "ruff"]}

    def test_console_scripts(self, tmp_path):
        _make_setup_cfg(tmp_path, {
            "metadata": {"name": "myapp"},
            "options.entry_points": {
                "console_scripts": "\n    myapp = myapp.cli:main",
            },
        })
        meta = parse_setup_cfg(tmp_path / "setup.cfg")
        assert meta.entry_points == {"myapp": "myapp.cli:main"}

    def test_missing_sections(self, tmp_path):
        _make_setup_cfg(tmp_path, {"tool:pytest": {"testpaths": "tests"}})
        meta = parse_setup_cfg(tmp_path / "setup.cfg")
        assert meta.name is None
        assert meta.dependencies == []


# ---------------------------------------------------------------------------
# parse_requirements_txt
# ---------------------------------------------------------------------------


class TestParseRequirementsTxt:
    def test_basic_deps(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("click>=8.0\nrequests>=2.28\n")
        meta = parse_requirements_txt(tmp_path / "requirements.txt")
        assert meta.dependencies == ["click>=8.0", "requests>=2.28"]

    def test_comments_and_blanks(self, tmp_path):
        (tmp_path / "requirements.txt").write_text(
            "# A comment\n\nclick>=8.0\n\n# Another\nrequests\n"
        )
        meta = parse_requirements_txt(tmp_path / "requirements.txt")
        assert meta.dependencies == ["click>=8.0", "requests"]

    def test_inline_comments(self, tmp_path):
        (tmp_path / "requirements.txt").write_text(
            "requests>=2.0  # HTTP library\n"
        )
        meta = parse_requirements_txt(tmp_path / "requirements.txt")
        assert meta.dependencies == ["requests>=2.0"]

    def test_recursive_include(self, tmp_path):
        (tmp_path / "base.txt").write_text("click>=8.0\n")
        (tmp_path / "requirements.txt").write_text("-r base.txt\nrequests\n")
        meta = parse_requirements_txt(tmp_path / "requirements.txt")
        assert "click>=8.0" in meta.dependencies
        assert "requests" in meta.dependencies

    def test_editable_skipped(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("-e ./local-pkg\nclick\n")
        meta = parse_requirements_txt(tmp_path / "requirements.txt")
        assert meta.dependencies == ["click"]
        assert any("editable" in w for w in meta.warnings)

    def test_index_options_skipped(self, tmp_path):
        (tmp_path / "requirements.txt").write_text(
            "--index-url https://pypi.org/simple\nclick\n"
        )
        meta = parse_requirements_txt(tmp_path / "requirements.txt")
        assert meta.dependencies == ["click"]

    def test_circular_include(self, tmp_path):
        (tmp_path / "a.txt").write_text("-r b.txt\nclick\n")
        (tmp_path / "b.txt").write_text("-r a.txt\nrequests\n")
        meta = parse_requirements_txt(tmp_path / "a.txt")
        assert "click" in meta.dependencies
        assert "requests" in meta.dependencies


# ---------------------------------------------------------------------------
# parse_existing_pyproject
# ---------------------------------------------------------------------------


class TestParseExistingPyproject:
    def test_extracts_all_fields(self, tmp_path):
        import tomli_w

        data = {
            "project": {
                "name": "myapp",
                "version": "1.0.0",
                "description": "My app",
                "requires-python": ">=3.11",
                "dependencies": ["click>=8.0"],
                "optional-dependencies": {"dev": ["pytest"]},
                "scripts": {"myapp": "myapp.cli:main"},
            },
        }
        (tmp_path / "pyproject.toml").write_bytes(tomli_w.dumps(data).encode())
        meta = parse_existing_pyproject(tmp_path / "pyproject.toml")
        assert meta.name == "myapp"
        assert meta.version == "1.0.0"
        assert meta.dependencies == ["click>=8.0"]
        assert meta.optional_dependencies == {"dev": ["pytest"]}
        assert meta.entry_points == {"myapp": "myapp.cli:main"}

    def test_partial_project(self, tmp_path):
        import tomli_w

        data = {"project": {"name": "myapp"}}
        (tmp_path / "pyproject.toml").write_bytes(tomli_w.dumps(data).encode())
        meta = parse_existing_pyproject(tmp_path / "pyproject.toml")
        assert meta.name == "myapp"
        assert meta.version is None
        assert meta.dependencies == []

    def test_no_project_section(self, tmp_path):
        import tomli_w

        data = {"tool": {"ruff": {"line-length": 88}}}
        (tmp_path / "pyproject.toml").write_bytes(tomli_w.dumps(data).encode())
        meta = parse_existing_pyproject(tmp_path / "pyproject.toml")
        assert meta.name is None


# ---------------------------------------------------------------------------
# merge_metadata
# ---------------------------------------------------------------------------


class TestMergeMetadata:
    def test_priority_order_scalars(self):
        high = ProjectMetadata(name="from-cfg", version="2.0", sources=["setup.cfg"])
        low = ProjectMetadata(name="from-py", version="1.0", sources=["setup.py"])
        merged = merge_metadata([high, low])
        assert merged.name == "from-cfg"
        assert merged.version == "2.0"

    def test_deps_highest_priority_wins(self):
        high = ProjectMetadata(dependencies=["click>=8.0"], sources=["setup.cfg"])
        low = ProjectMetadata(dependencies=["click>=7.0", "flask"], sources=["requirements.txt"])
        merged = merge_metadata([high, low])
        assert merged.dependencies == ["click>=8.0"]

    def test_optional_deps_merged(self):
        high = ProjectMetadata(
            optional_dependencies={"dev": ["pytest"]}, sources=["setup.cfg"],
        )
        low = ProjectMetadata(
            optional_dependencies={"dev": ["ruff"], "docs": ["sphinx"]},
            sources=["setup.py"],
        )
        merged = merge_metadata([high, low])
        assert merged.optional_dependencies["dev"] == ["pytest"]  # high priority
        assert merged.optional_dependencies["docs"] == ["sphinx"]  # only in low

    def test_warnings_aggregated(self):
        a = ProjectMetadata(warnings=["warn1"], sources=["setup.py"])
        b = ProjectMetadata(warnings=["warn2"], sources=["setup.cfg"])
        merged = merge_metadata([b, a])
        assert "warn1" in merged.warnings
        assert "warn2" in merged.warnings

    def test_fills_gaps(self):
        high = ProjectMetadata(name="myapp", sources=["setup.cfg"])
        low = ProjectMetadata(version="1.0", description="desc", sources=["setup.py"])
        merged = merge_metadata([high, low])
        assert merged.name == "myapp"
        assert merged.version == "1.0"
        assert merged.description == "desc"


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_base_wins(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 1}

    def test_overlay_fills_gaps(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_nested_dicts_recurse(self):
        base = {"project": {"name": "myapp"}}
        overlay = {"project": {"name": "other", "version": "1.0"}}
        result = _deep_merge(base, overlay)
        assert result["project"]["name"] == "myapp"
        assert result["project"]["version"] == "1.0"


# ---------------------------------------------------------------------------
# build_pyproject_dict
# ---------------------------------------------------------------------------


class TestBuildPyprojectDict:
    def test_full_metadata(self):
        meta = ProjectMetadata(
            name="myapp", version="1.0.0", description="Cool",
            requires_python=">=3.11", dependencies=["click>=8.0"],
            optional_dependencies={"dev": ["pytest"]},
            entry_points={"myapp": "myapp.cli:main"},
        )
        d = build_pyproject_dict(meta, "myapp")
        assert d["project"]["name"] == "myapp"
        assert d["project"]["version"] == "1.0.0"
        assert d["project"]["dependencies"] == ["click>=8.0"]
        assert d["project"]["scripts"] == {"myapp": "myapp.cli:main"}
        assert d["build-system"]["build-backend"] == "hatchling.build"

    def test_defaults(self):
        meta = ProjectMetadata()
        d = build_pyproject_dict(meta, "my-project")
        assert d["project"]["name"] == "my-project"
        assert d["project"]["version"] == "0.1.0"
        assert d["project"]["requires-python"] == ">=3.10"

    def test_no_empty_sections(self):
        meta = ProjectMetadata(name="myapp")
        d = build_pyproject_dict(meta, "myapp")
        assert "dependencies" not in d["project"]
        assert "optional-dependencies" not in d["project"]
        assert "scripts" not in d["project"]


# ---------------------------------------------------------------------------
# write_pyproject
# ---------------------------------------------------------------------------


class TestWritePyproject:
    def test_writes_new_file(self, tmp_path):
        data = {"project": {"name": "myapp", "version": "1.0"}}
        write_pyproject(tmp_path, data)
        with open(tmp_path / "pyproject.toml", "rb") as f:
            result = tomllib.load(f)
        assert result["project"]["name"] == "myapp"

    def test_merges_with_existing(self, tmp_path):
        import tomli_w

        existing = {
            "build-system": {"requires": ["flit_core"], "build-backend": "flit_core.buildapi"},
            "project": {"name": "myapp"},
        }
        (tmp_path / "pyproject.toml").write_bytes(tomli_w.dumps(existing).encode())

        overlay = {
            "build-system": {"requires": ["hatchling"], "build-backend": "hatchling.build"},
            "project": {"name": "other", "version": "1.0"},
        }
        write_pyproject(tmp_path, overlay)

        with open(tmp_path / "pyproject.toml", "rb") as f:
            result = tomllib.load(f)
        # Existing values preserved
        assert result["build-system"]["build-backend"] == "flit_core.buildapi"
        assert result["project"]["name"] == "myapp"
        # New values filled in
        assert result["project"]["version"] == "1.0"


# ---------------------------------------------------------------------------
# migrate_project (integration)
# ---------------------------------------------------------------------------


class TestMigrateProject:
    def test_setup_py_only(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        _make_setup_py(
            proj, name="myapp", version="1.0.0",
            install_requires=["click>=8.0", "requests"],
        )
        result = migrate_project(proj)
        assert not result.skipped
        assert "setup.py" in result.sources_found

        with open(proj / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["name"] == "myapp"
        assert data["project"]["dependencies"] == ["click>=8.0", "requests"]

    def test_setup_cfg_only(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        _make_setup_cfg(proj, {
            "metadata": {"name": "myapp", "version": "2.0"},
            "options": {"install_requires": "\n    flask>=2.0"},
        })
        result = migrate_project(proj)
        assert not result.skipped

        with open(proj / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["name"] == "myapp"
        assert data["project"]["dependencies"] == ["flask>=2.0"]

    def test_requirements_txt_only(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        (proj / "requirements.txt").write_text("click>=8.0\nrequests\n")
        result = migrate_project(proj)
        assert not result.skipped

        with open(proj / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["name"] == "myapp"  # falls back to dir name
        assert data["project"]["dependencies"] == ["click>=8.0", "requests"]

    def test_priority_order(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        _make_setup_py(proj, name="from-setup-py", version="1.0")
        _make_setup_cfg(proj, {
            "metadata": {"name": "from-setup-cfg", "version": "2.0"},
        })
        result = migrate_project(proj)

        with open(proj / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        # setup.cfg has higher priority
        assert data["project"]["name"] == "from-setup-cfg"
        assert data["project"]["version"] == "2.0"

    def test_clean_removes_legacy(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        _make_setup_py(proj, name="myapp")
        (proj / "requirements.txt").write_text("click\n")
        result = migrate_project(proj, clean=True)
        assert "setup.py" in result.files_removed
        assert "requirements.txt" in result.files_removed
        assert not (proj / "setup.py").exists()
        assert not (proj / "requirements.txt").exists()
        assert (proj / "pyproject.toml").exists()

    def test_clean_false_preserves(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        _make_setup_py(proj, name="myapp")
        migrate_project(proj, clean=False)
        assert (proj / "setup.py").exists()
        assert (proj / "pyproject.toml").exists()

    def test_no_legacy_files_skipped(self, tmp_path):
        proj = tmp_path / "myapp"
        proj.mkdir()
        result = migrate_project(proj)
        assert result.skipped

    def test_existing_pyproject_supplemented(self, tmp_path):
        import tomli_w

        proj = tmp_path / "myapp"
        proj.mkdir()
        existing = {"project": {"name": "myapp"}}
        (proj / "pyproject.toml").write_bytes(tomli_w.dumps(existing).encode())
        _make_setup_py(proj, name="other", version="1.0", install_requires=["click"])

        result = migrate_project(proj)
        assert not result.skipped

        with open(proj / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        # Existing name preserved
        assert data["project"]["name"] == "myapp"
        # Version filled from setup.py
        assert data["project"]["version"] == "1.0"


# ---------------------------------------------------------------------------
# migrate_projects (top-level)
# ---------------------------------------------------------------------------


class TestMigrateProjects:
    def test_multiple_projects(self, tmp_path):
        for name in ["svc-a", "svc-b"]:
            proj = tmp_path / name
            proj.mkdir()
            _make_setup_py(proj, name=name, version="1.0")

        migrate_projects(tmp_path, None)

        for name in ["svc-a", "svc-b"]:
            assert (tmp_path / name / "pyproject.toml").exists()

    def test_project_name_filter(self, tmp_path):
        for name in ["svc-a", "svc-b"]:
            proj = tmp_path / name
            proj.mkdir()
            _make_setup_py(proj, name=name)

        migrate_projects(tmp_path, ("svc-a",))
        assert (tmp_path / "svc-a" / "pyproject.toml").exists()
        assert not (tmp_path / "svc-b" / "pyproject.toml").exists()

    def test_skips_hidden_dirs(self, tmp_path):
        proj = tmp_path / ".hidden"
        proj.mkdir()
        _make_setup_py(proj, name="hidden")

        migrate_projects(tmp_path, None)
        assert not (proj / "pyproject.toml").exists()
