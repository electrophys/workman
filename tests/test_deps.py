import json
from pathlib import Path
from unittest.mock import patch

import pytest
from packaging.version import Version

from workman.deps import (
    OutdatedInfo,
    _is_simple_gte,
    _parse_deps,
    _update_dep_line,
    align_dependencies,
    find_mismatches,
    find_outdated,
    get_latest_version,
    highest_minimum,
    scan_dependencies,
    upgrade_dependencies,
)


PYPROJECT_TEMPLATE = """\
[project]
name = "{name}"
version = "0.1.0"
dependencies = [
{main_deps}
]

[project.optional-dependencies]
extra = [
{opt_deps}
]

[dependency-groups]
dev = [
{dev_deps}
]
"""


def _make_project(tmp_path: Path, name: str, *, main=(), opt=(), dev=()):
    proj = tmp_path / name
    proj.mkdir()
    main_deps = "\n".join(f'    "{d}",' for d in main)
    opt_deps = "\n".join(f'    "{d}",' for d in opt)
    dev_deps = "\n".join(f'    "{d}",' for d in dev)
    (proj / "pyproject.toml").write_text(
        PYPROJECT_TEMPLATE.format(
            name=name, main_deps=main_deps, opt_deps=opt_deps, dev_deps=dev_deps,
        )
    )


class TestParseDeps:
    def test_basic(self):
        result = _parse_deps(["click>=8.0", "requests>=2.28.0"])
        assert result == {"click": ">=8.0", "requests": ">=2.28.0"}

    def test_normalizes_name(self):
        result = _parse_deps(["PyYAML>=6.0"])
        assert "pyyaml" in result

    def test_no_specifier(self):
        result = _parse_deps(["requests"])
        assert result == {"requests": ""}

    def test_skips_invalid(self):
        result = _parse_deps(["valid>=1.0", "not a valid dep!!!"])
        assert "valid" in result
        assert len(result) == 1


class TestScanDependencies:
    def test_scans_main_deps(self, tmp_path):
        _make_project(tmp_path, "svc-a", main=["requests>=2.28.0", "click>=8.0"])
        _make_project(tmp_path, "svc-b", main=["requests>=2.31.0"])
        result = scan_dependencies(tmp_path)
        assert "requests" in result
        assert result["requests"]["svc-a"] == ">=2.28.0"
        assert result["requests"]["svc-b"] == ">=2.31.0"

    def test_scans_optional_deps(self, tmp_path):
        _make_project(tmp_path, "proj", opt=["boto3>=1.28"])
        result = scan_dependencies(tmp_path)
        assert "boto3" in result

    def test_scans_dev_deps(self, tmp_path):
        _make_project(tmp_path, "proj", dev=["pytest>=7.0"])
        result = scan_dependencies(tmp_path)
        assert "pytest" in result

    def test_filters_by_project_names(self, tmp_path):
        _make_project(tmp_path, "a", main=["click>=8.0"])
        _make_project(tmp_path, "b", main=["click>=7.0"])
        result = scan_dependencies(tmp_path, ("a",))
        assert result["click"] == {"a": ">=8.0"}

    def test_skips_hidden_dirs(self, tmp_path):
        _make_project(tmp_path, ".hidden", main=["foo>=1.0"])
        result = scan_dependencies(tmp_path)
        assert "foo" not in result

    def test_skips_dirs_without_pyproject(self, tmp_path):
        (tmp_path / "empty").mkdir()
        result = scan_dependencies(tmp_path)
        assert result == {}


class TestFindMismatches:
    def test_no_mismatches(self):
        pkgs = {"click": {"a": ">=8.0", "b": ">=8.0"}}
        assert find_mismatches(pkgs) == {}

    def test_detects_mismatches(self):
        pkgs = {"click": {"a": ">=8.0", "b": ">=7.0"}}
        result = find_mismatches(pkgs)
        assert "click" in result

    def test_single_project_not_mismatch(self):
        pkgs = {"click": {"a": ">=8.0"}}
        assert find_mismatches(pkgs) == {}


class TestHighestMinimum:
    def test_picks_highest(self):
        specs = {"a": ">=2.28.0", "b": ">=2.31.0", "c": ">=2.25.0"}
        assert highest_minimum(specs) == ">=2.31.0"

    def test_returns_none_for_exact_pin(self):
        specs = {"a": ">=2.28.0", "b": "==2.31.0"}
        assert highest_minimum(specs) is None

    def test_returns_none_for_complex_range(self):
        specs = {"a": ">=2.0,<3.0", "b": ">=2.5"}
        assert highest_minimum(specs) is None

    def test_empty_specifier_treated_as_any(self):
        specs = {"a": "", "b": ">=1.0"}
        assert highest_minimum(specs) == ">=1.0"

    def test_all_empty(self):
        specs = {"a": "", "b": ""}
        assert highest_minimum(specs) is None


class TestIsSimpleGte:
    def test_empty(self):
        assert _is_simple_gte("") is True

    def test_simple_gte(self):
        assert _is_simple_gte(">=1.0") is True

    def test_exact_pin(self):
        assert _is_simple_gte("==1.0") is False

    def test_upper_bound(self):
        assert _is_simple_gte(">=1.0,<2.0") is False


class TestUpdateDepLine:
    def test_replaces_specifier(self):
        content = 'dependencies = [\n    "click>=7.0",\n]'
        result = _update_dep_line(content, "click", ">=8.0")
        assert '"click>=8.0"' in result

    def test_adds_specifier_where_none(self):
        content = 'dependencies = [\n    "click",\n]'
        result = _update_dep_line(content, "click", ">=8.0")
        assert '"click>=8.0"' in result

    def test_case_insensitive(self):
        content = 'dependencies = [\n    "Click>=7.0",\n]'
        result = _update_dep_line(content, "click", ">=8.0")
        assert "Click>=8.0" in result


class TestAlignDependencies:
    def test_updates_files(self, tmp_path):
        _make_project(tmp_path, "a", main=["requests>=2.28.0"])
        _make_project(tmp_path, "b", main=["requests>=2.31.0"])

        mismatches = {"requests": {"a": ">=2.28.0", "b": ">=2.31.0"}}
        align_dependencies(tmp_path, mismatches)

        content_a = (tmp_path / "a" / "pyproject.toml").read_text()
        assert "requests>=2.31.0" in content_a

    def test_skips_complex_specifiers(self, tmp_path):
        _make_project(tmp_path, "a", main=["pydantic>=2.0,<3.0"])
        _make_project(tmp_path, "b", main=["pydantic==2.5.0"])

        original_a = (tmp_path / "a" / "pyproject.toml").read_text()
        original_b = (tmp_path / "b" / "pyproject.toml").read_text()

        mismatches = {"pydantic": {"a": ">=2.0,<3.0", "b": "==2.5.0"}}
        align_dependencies(tmp_path, mismatches)

        assert (tmp_path / "a" / "pyproject.toml").read_text() == original_a
        assert (tmp_path / "b" / "pyproject.toml").read_text() == original_b


# ---------------------------------------------------------------------------
# PyPI outdated / upgrade tests
# ---------------------------------------------------------------------------


def _mock_pypi_response(version: str):
    """Create a mock urlopen context manager returning a fake PyPI JSON response."""
    data = json.dumps({"info": {"version": version}}).encode()

    class FakeResponse:
        def read(self):
            return data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return FakeResponse()


class TestGetLatestVersion:
    @patch("workman.deps.urllib.request.urlopen")
    def test_returns_version(self, mock_urlopen):
        mock_urlopen.return_value = _mock_pypi_response("2.32.3")
        result = get_latest_version("requests")
        assert result == Version("2.32.3")

    @patch("workman.deps.urllib.request.urlopen")
    def test_returns_none_on_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("no network")
        assert get_latest_version("requests") is None

    @patch("workman.deps.urllib.request.urlopen")
    def test_returns_none_on_bad_json(self, mock_urlopen):
        class FakeResponse:
            def read(self):
                return b"not json"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        mock_urlopen.return_value = FakeResponse()
        assert get_latest_version("requests") is None


class TestFindOutdated:
    @patch("workman.deps.get_latest_version")
    def test_detects_outdated(self, mock_latest):
        mock_latest.return_value = Version("2.32.3")
        packages = {"requests": {"a": ">=2.28.0", "b": ">=2.31.0"}}
        result = find_outdated(packages)
        assert "requests" in result
        assert result["requests"].latest == Version("2.32.3")
        assert result["requests"].current_min == Version("2.31.0")

    @patch("workman.deps.get_latest_version")
    def test_skips_up_to_date(self, mock_latest):
        mock_latest.return_value = Version("8.0.0")
        packages = {"click": {"a": ">=8.0.0"}}
        result = find_outdated(packages)
        assert "click" not in result

    @patch("workman.deps.get_latest_version")
    def test_skips_when_pypi_fails(self, mock_latest):
        mock_latest.return_value = None
        packages = {"click": {"a": ">=7.0"}}
        result = find_outdated(packages)
        assert result == {}

    @patch("workman.deps.get_latest_version")
    def test_skips_bare_names(self, mock_latest):
        packages = {"click": {"a": ""}}
        result = find_outdated(packages)
        assert result == {}
        mock_latest.assert_not_called()

    @patch("workman.deps.get_latest_version")
    def test_marks_complex_specifiers(self, mock_latest):
        mock_latest.return_value = Version("3.0.0")
        packages = {"pydantic": {"a": ">=2.0,<3.0"}}
        result = find_outdated(packages)
        assert "pydantic" in result
        assert result["pydantic"].simple is False


class TestUpgradeDependencies:
    @patch("workman.deps.get_latest_version")
    def test_updates_files(self, mock_latest, tmp_path):
        _make_project(tmp_path, "a", main=["requests>=2.28.0"])
        _make_project(tmp_path, "b", main=["requests>=2.31.0"])

        packages = {"requests": {"a": ">=2.28.0", "b": ">=2.31.0"}}
        outdated = {
            "requests": OutdatedInfo(
                current_min=Version("2.31.0"),
                latest=Version("2.32.3"),
                simple=True,
            ),
        }
        upgrade_dependencies(tmp_path, packages, outdated)

        assert "requests>=2.32.3" in (tmp_path / "a" / "pyproject.toml").read_text()
        assert "requests>=2.32.3" in (tmp_path / "b" / "pyproject.toml").read_text()

    @patch("workman.deps.get_latest_version")
    def test_skips_complex_specifiers(self, mock_latest, tmp_path):
        _make_project(tmp_path, "a", main=["pydantic>=2.0,<3.0"])

        original = (tmp_path / "a" / "pyproject.toml").read_text()
        packages = {"pydantic": {"a": ">=2.0,<3.0"}}
        outdated = {
            "pydantic": OutdatedInfo(
                current_min=Version("2.0"),
                latest=Version("3.0.0"),
                simple=False,
            ),
        }
        upgrade_dependencies(tmp_path, packages, outdated)

        assert (tmp_path / "a" / "pyproject.toml").read_text() == original
