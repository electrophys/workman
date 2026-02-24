from pathlib import Path

import pytest
import yaml

from workman.config import (
    ImageConfig,
    WorkspaceConfig,
    get_build_context,
    get_docker_projects,
    get_effective_latest_tag,
    load_config,
    resolve_projects,
)


def _write_config(tmp_path: Path, data: dict) -> Path:
    config_path = tmp_path / ".workman.yaml"
    config_path.write_text(yaml.dump(data))
    return tmp_path


class TestLoadConfig:
    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No .workman.yaml found"):
            load_config(tmp_path)

    def test_empty_config(self, tmp_path):
        _write_config(tmp_path, {})
        ws = load_config(tmp_path)
        assert ws.root == tmp_path
        assert ws.latest_tag == "latest"
        assert ws.projects == {}

    def test_loads_projects_with_images(self, tmp_path):
        _write_config(tmp_path, {
            "latest_tag": "stable",
            "projects": {
                "app": {
                    "images": [
                        {"name": "myorg/app"},
                        {"name": "myorg/app-worker", "dockerfile": "Dockerfile.worker"},
                    ],
                },
            },
        })
        ws = load_config(tmp_path)
        assert ws.latest_tag == "stable"
        assert "app" in ws.projects
        proj = ws.projects["app"]
        assert len(proj.images) == 2
        assert proj.images[0].name == "myorg/app"
        assert proj.images[0].dockerfile is None
        assert proj.images[1].name == "myorg/app-worker"
        assert proj.images[1].dockerfile == "Dockerfile.worker"

    def test_image_context_resolved_relative_to_root(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {
                "svc": {
                    "images": [
                        {"name": "svc", "context": "services/svc"},
                    ],
                },
            },
        })
        ws = load_config(tmp_path)
        assert ws.projects["svc"].images[0].context == tmp_path / "services/svc"

    def test_project_with_no_images(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {"empty": {}},
        })
        ws = load_config(tmp_path)
        assert ws.projects["empty"].images == []

    def test_per_project_latest_tag(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {
                "app": {"latest_tag": "edge", "images": [{"name": "app"}]},
            },
        })
        ws = load_config(tmp_path)
        assert ws.projects["app"].latest_tag == "edge"

    def test_null_project_value(self, tmp_path):
        """A project key with no value (null in YAML) should not crash."""
        (tmp_path / ".workman.yaml").write_text(
            "projects:\n  myapp:\n"
        )
        ws = load_config(tmp_path)
        assert ws.projects["myapp"].images == []

    def test_default_latest_tag_when_omitted(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {"app": {"images": [{"name": "app"}]}},
        })
        ws = load_config(tmp_path)
        assert ws.latest_tag == "latest"

    def test_image_as_plain_string(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {
                "app": {
                    "images": ["myorg/app", "myorg/app-worker"],
                },
            },
        })
        ws = load_config(tmp_path)
        assert len(ws.projects["app"].images) == 2
        assert ws.projects["app"].images[0].name == "myorg/app"
        assert ws.projects["app"].images[0].dockerfile is None
        assert ws.projects["app"].images[0].context is None
        assert ws.projects["app"].images[1].name == "myorg/app-worker"

    def test_image_mixed_strings_and_dicts(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {
                "app": {
                    "images": [
                        "myorg/app",
                        {"name": "myorg/app-worker", "dockerfile": "Dockerfile.worker"},
                    ],
                },
            },
        })
        ws = load_config(tmp_path)
        imgs = ws.projects["app"].images
        assert imgs[0].name == "myorg/app"
        assert imgs[0].dockerfile is None
        assert imgs[1].name == "myorg/app-worker"
        assert imgs[1].dockerfile == "Dockerfile.worker"

    def test_image_with_all_fields(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {
                "svc": {
                    "images": [{
                        "name": "registry.io/org/svc",
                        "dockerfile": "Dockerfile.prod",
                        "context": "services/svc",
                    }],
                },
            },
        })
        ws = load_config(tmp_path)
        img = ws.projects["svc"].images[0]
        assert img.name == "registry.io/org/svc"
        assert img.dockerfile == "Dockerfile.prod"
        assert img.context == tmp_path / "services/svc"

    def test_multiple_projects_mixed_configs(self, tmp_path):
        _write_config(tmp_path, {
            "latest_tag": "stable",
            "projects": {
                "frontend": {
                    "images": [{"name": "fe"}],
                },
                "backend": {
                    "latest_tag": "edge",
                    "images": [
                        {"name": "be-api", "dockerfile": "Dockerfile.api"},
                        {"name": "be-worker", "context": "worker"},
                    ],
                },
                "lib": {},
            },
        })
        ws = load_config(tmp_path)
        assert ws.latest_tag == "stable"

        fe = ws.projects["frontend"]
        assert len(fe.images) == 1
        assert fe.latest_tag is None

        be = ws.projects["backend"]
        assert len(be.images) == 2
        assert be.latest_tag == "edge"
        assert be.images[0].dockerfile == "Dockerfile.api"
        assert be.images[0].context is None
        assert be.images[1].context == tmp_path / "worker"
        assert be.images[1].dockerfile is None

        lib = ws.projects["lib"]
        assert lib.images == []


class TestGetBuildContext:
    def test_defaults_to_project_path(self):
        from workman.config import ProjectConfig
        proj = ProjectConfig(name="x", path=Path("/ws/x"))
        img = ImageConfig(name="x")
        assert get_build_context(proj, img) == Path("/ws/x")

    def test_uses_image_context_when_set(self):
        from workman.config import ProjectConfig
        proj = ProjectConfig(name="x", path=Path("/ws/x"))
        img = ImageConfig(name="x", context=Path("/ws/other"))
        assert get_build_context(proj, img) == Path("/ws/other")


class TestGetEffectiveLatestTag:
    def test_falls_back_to_workspace(self):
        from workman.config import ProjectConfig
        ws = WorkspaceConfig(root=Path("/ws"), latest_tag="prod")
        proj = ProjectConfig(name="a", path=Path("/ws/a"))
        assert get_effective_latest_tag(ws, proj) == "prod"

    def test_project_override(self):
        from workman.config import ProjectConfig
        ws = WorkspaceConfig(root=Path("/ws"), latest_tag="prod")
        proj = ProjectConfig(name="a", path=Path("/ws/a"), latest_tag="edge")
        assert get_effective_latest_tag(ws, proj) == "edge"


class TestGetDockerProjects:
    def test_returns_only_projects_with_images(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {
                "has": {"images": [{"name": "img"}]},
                "empty": {},
            },
        })
        ws = load_config(tmp_path)
        result = get_docker_projects(ws)
        assert [p.name for p in result] == ["has"]

    def test_filters_by_name(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {
                "a": {"images": [{"name": "a"}]},
                "b": {"images": [{"name": "b"}]},
            },
        })
        ws = load_config(tmp_path)
        result = get_docker_projects(ws, ("b",))
        assert [p.name for p in result] == ["b"]

    def test_raises_on_missing_name(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {
                "a": {"images": [{"name": "a"}]},
            },
        })
        ws = load_config(tmp_path)
        with pytest.raises(ValueError, match="nope"):
            get_docker_projects(ws, ("nope",))


class TestLoadGroups:
    def test_no_groups(self, tmp_path):
        _write_config(tmp_path, {"projects": {"a": {}}})
        ws = load_config(tmp_path)
        assert ws.groups == {}
        assert ws.default_group is None

    def test_loads_groups(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {"a": {}, "b": {}, "c": {}},
            "groups": {
                "frontend": ["a", "b"],
                "backend": ["c"],
            },
        })
        ws = load_config(tmp_path)
        assert ws.groups == {"frontend": ["a", "b"], "backend": ["c"]}
        assert ws.default_group is None

    def test_loads_default_group(self, tmp_path):
        _write_config(tmp_path, {
            "projects": {"a": {}, "b": {}},
            "groups": {
                "fe": ["a"],
                "default_group": "fe",
            },
        })
        ws = load_config(tmp_path)
        assert ws.groups == {"fe": ["a"]}
        assert ws.default_group == "fe"


class TestResolveProjects:
    def _ws(self):
        return WorkspaceConfig(
            root=Path("/ws"),
            projects={
                "a": None, "b": None, "c": None, "d": None,
            },
            groups={"frontend": ["a", "b"], "backend": ["c", "d"]},
        )

    def test_no_args_no_default_returns_none(self):
        ws = self._ws()
        assert resolve_projects(ws, ()) is None

    def test_no_args_with_default_group(self):
        ws = self._ws()
        ws.default_group = "frontend"
        assert resolve_projects(ws, ()) == ("a", "b")

    def test_at_all_returns_none(self):
        ws = self._ws()
        assert resolve_projects(ws, ("@all",)) is None

    def test_at_all_mixed_still_returns_none(self):
        ws = self._ws()
        assert resolve_projects(ws, ("a", "@all")) is None

    def test_expand_group(self):
        ws = self._ws()
        assert resolve_projects(ws, ("@frontend",)) == ("a", "b")

    def test_expand_multiple_groups(self):
        ws = self._ws()
        result = resolve_projects(ws, ("@frontend", "@backend"))
        assert result == ("a", "b", "c", "d")

    def test_mix_names_and_groups(self):
        ws = self._ws()
        result = resolve_projects(ws, ("c", "@frontend"))
        assert result == ("c", "a", "b")

    def test_deduplicates(self):
        ws = self._ws()
        result = resolve_projects(ws, ("a", "@frontend"))
        assert result == ("a", "b")

    def test_unknown_group_raises(self):
        ws = self._ws()
        with pytest.raises(ValueError, match="Unknown group: nope"):
            resolve_projects(ws, ("@nope",))
