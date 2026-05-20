#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_VERSION="$(
    uv run python - <<'PY'
import ast
import tomllib
from pathlib import Path

project = tomllib.loads(Path("pyproject.toml").read_text())
project_version = project["project"]["version"]

tree = ast.parse(Path("src/hive_mp_cli/__init__.py").read_text())
init_version = None
for node in tree.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                init_version = ast.literal_eval(node.value)

if init_version is None:
    raise SystemExit("src/hive_mp_cli/__init__.py does not define __version__")

if init_version != project_version:
    raise SystemExit(
        f"version mismatch: pyproject.toml has {project_version}, "
        f"src/hive_mp_cli/__init__.py has {init_version}"
    )

print(project_version)
PY
)"

RELEASE_TAG="${RELEASE_TAG:-${GITHUB_REF_NAME:-}}"
RELEASE_TAG="${RELEASE_TAG#refs/tags/}"

if [[ -n "$RELEASE_TAG" ]]; then
    if [[ ! "$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "release tag must look like vX.Y.Z, got: $RELEASE_TAG" >&2
        exit 1
    fi

    TAG_VERSION="${RELEASE_TAG#v}"
    if [[ "$TAG_VERSION" != "$PROJECT_VERSION" ]]; then
        echo "release tag/version mismatch: $RELEASE_TAG vs pyproject $PROJECT_VERSION" >&2
        exit 1
    fi
fi

rm -rf dist
uv build --sdist --wheel --out-dir dist

WHEEL="dist/hive_mp_cli-${PROJECT_VERSION}-py3-none-any.whl"
SDIST="dist/hive_mp_cli-${PROJECT_VERSION}.tar.gz"
SKILL_TARBALL="dist/hive-mp-cli-skill.tar.gz"

for asset in "$WHEEL" "$SDIST"; do
    if [[ ! -f "$asset" ]]; then
        echo "expected build asset missing: $asset" >&2
        exit 1
    fi
done

if [[ ! -f skill/SKILL.md ]]; then
    echo "skill/SKILL.md is missing" >&2
    exit 1
fi

COPYFILE_DISABLE=1 tar -czf "$SKILL_TARBALL" -C skill .

if [[ ! -f "$SKILL_TARBALL" ]]; then
    echo "expected skill asset missing: $SKILL_TARBALL" >&2
    exit 1
fi

echo "Built release assets:"
ls -lh "$WHEEL" "$SDIST" "$SKILL_TARBALL"
