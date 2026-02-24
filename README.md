# Workman

CLI tool for managing a workspace of projects. A workspace is a directory containing subproject folders that may be git repos, dockerized applications, or both.

Workman lets you:

- View **git status** across the workspace repo and all subprojects at once
- **Build** Docker images with automatic date-based tagging (`YYYYMMDD-N`)
- **Push** images to registries
- **Prune** old Docker images, keeping only the most recent
- **Clean** Python build artifacts across all projects
- **Initialize** a workspace config by scanning projects and local Docker images
- **Manage .gitignore** to exclude subproject folders from the workspace repo

## Installation

Requires Python 3.13+.

### As a uv tool (recommended)

Install globally so `wm` is available everywhere:

```bash
uv tool install git+https://github.com/electrophys/workman.git
```

To upgrade later:

```bash
uv tool upgrade workman
```

### From a local clone

```bash
git clone https://github.com/electrophys/workman.git
cd workman
uv tool install .
```

## Usage

Run `wm` from your workspace root (the directory containing your subproject folders).

```
wm [OPTIONS] COMMAND [ARGS]...

Options:
  -C DIRECTORY  Workspace root directory (default: current directory).
  --help        Show this message and exit.

Commands:
  init       Scan the workspace and generate a .workman.yaml config file.
  status     Show git status for the workspace repo and all subprojects.
  build      Build docker images for projects (all if none specified).
  push       Push docker images to their registries.
  prune      Remove all docker images except the most recent for each project.
  clean      Remove Python build artifacts from all projects.
  gitignore  Update .gitignore to exclude subproject folders.
```

Use `-C` to target a workspace without `cd`-ing into it:

```bash
wm -C /path/to/workspace status
```

### Build and push specific projects

```bash
wm build myapp backend    # build only these two
wm push myapp             # push only myapp
```

### Initialize a workspace

Generate a `.workman.yaml` automatically by scanning subdirectories for Dockerfiles and matching folder names against local Docker images. This also creates a `.gitignore` to exclude subproject folders from the workspace repo:

```bash
wm init
```

### Manage .gitignore

If you add or remove projects from `.workman.yaml`, refresh the `.gitignore`:

```bash
wm gitignore
```

This maintains a managed block in `.gitignore` listing each project folder, while preserving any entries you've added manually.

### Workspace as a git repo

The workspace root can itself be a git repo for tracking workspace configuration (`.workman.yaml`, `.devcontainer/`, VS Code settings, etc.). When it is, `wm status` shows the workspace repo's status first, followed by subproject statuses. Use `wm init` or `wm gitignore` to keep subproject folders excluded.

## Configuration

You can also create a `.workman.yaml` manually in your workspace root:

```yaml
latest_tag: latest            # default tag applied alongside the date tag

projects:
  myapp:
    latest_tag: stable        # per-project override
    images:
      - name: registry.example.com/myapp
  backend:
    images:
      - name: myorg/backend-api
        dockerfile: Dockerfile.api
        context: services/backend   # relative to workspace root
      - name: myorg/backend-worker
        dockerfile: Dockerfile.worker
```

Each project has an `images` list. Each image entry supports:

- **`name`** (required) — the Docker image name. Include a registry prefix for push support.
- **`dockerfile`** (optional) — Dockerfile path relative to the build context. Defaults to `Dockerfile`.
- **`context`** (optional) — build context directory relative to the workspace root. Defaults to the project subfolder.

Top-level and per-project options:

- **`latest_tag`** (top-level) — the tag applied to every new build alongside the `YYYYMMDD-N` tag. Defaults to `latest`.
- **`projects.<name>.latest_tag`** — override the global `latest_tag` for this project.

## License

GPL-3.0-or-later
