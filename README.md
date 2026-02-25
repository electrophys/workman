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
  deps       Report and align dependency versions across projects.
  migrate    Migrate legacy Python projects to pyproject.toml.
```

Use `-C` to target a workspace without `cd`-ing into it:

```bash
wm -C /path/to/workspace status
```

### Target specific projects or groups

Pass project names or `@group` references to any command:

```bash
wm build myapp backend    # build only these two
wm push myapp             # push only myapp
wm status @frontend       # status for the frontend group
wm build @backend extra   # build the backend group plus 'extra'
wm clean @all             # explicitly target all projects
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

### Align dependency versions

Check for packages that appear in multiple subprojects at different versions:

```bash
wm deps                 # report mismatches across all projects
wm deps @backend        # check only the backend group
wm deps --fix           # align to the highest >= lower bound
```

The command scans `pyproject.toml` files for `[project].dependencies`, `[project.optional-dependencies]`, and `[dependency-groups]`. In report mode it shows each package where version specifiers differ. With `--fix`, simple `>=X.Y.Z` specifiers are updated to the highest minimum found; exact pins (`==`) and complex ranges are left alone.

Check PyPI for newer versions of your dependencies:

```bash
wm deps --outdated      # report packages behind PyPI
wm deps --upgrade       # bump >= specifiers to latest PyPI versions
```

`--outdated` queries PyPI for each package and reports where the latest release is newer than the current `>=` lower bound. `--upgrade` does the same but also updates the specifiers in `pyproject.toml`. Complex specifiers (exact pins, upper bounds) are reported but left untouched.

### Migrate legacy projects

Convert projects that use `setup.py`, `setup.cfg`, or `requirements.txt` to a proper `pyproject.toml`:

```bash
wm migrate                # migrate all projects with legacy files
wm migrate svc-api        # migrate a specific project
wm migrate --clean        # also remove legacy files after migration
```

The command parses each legacy file and merges the extracted metadata (name, version, dependencies, entry points, etc.) into a `pyproject.toml` with a hatchling build system. When multiple sources exist, priority is: existing `pyproject.toml` > `setup.cfg` > `setup.py` > `requirements.txt`. Fields that can't be statically analyzed (e.g. dynamic versions in `setup.py`) are skipped with a warning.

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

### Groups

Define named subsets of projects for convenient targeting:

```yaml
groups:
  frontend:
    - myapp
  backend:
    - backend
  default_group: backend   # used when no projects are specified
```

- Use `@groupname` on any command: `wm build @frontend`
- `@all` is a built-in group meaning every project
- `default_group` sets which group is used when you run a command with no arguments (e.g. `wm build` with a default builds only that group instead of everything)

## License

GPL-3.0-or-later
