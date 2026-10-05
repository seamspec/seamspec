"""Runner presets and language detection at `init` (SPEC §12A.2, §12A.7)."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from .config import RunnerCfg

V01_PRESETS = ("pytest", "vitest")
LATER_PRESETS = ("jest", "go", "cargo")  # detected, but supported from v0.2


def _templates():
    return files("seamspec.templates")


def preset_toml(name: str) -> str:
    """The commented TOML table written into config.toml for this preset."""
    return _templates().joinpath("runners", f"{name}.toml").read_text("utf-8")


def preset(name: str) -> RunnerCfg:
    data = tomllib.loads(preset_toml(name))
    return RunnerCfg.model_validate(data["runners"][name])


@dataclass
class Detection:
    runners: list[str] = field(default_factory=list)  # v0.1 presets to enable
    unsupported: list[str] = field(default_factory=list)  # found, but not supported until v0.2
    notes: list[str] = field(default_factory=list)


def _package_json_deps(root: Path) -> set[str]:
    path = root / "package.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps |= set(section)
    return deps


def detect(root: Path) -> Detection:
    found = Detection()
    if any((root / m).is_file() for m in ("pyproject.toml", "setup.py", "setup.cfg")) or any(
        root.glob("requirements*.txt")
    ):
        found.runners.append("pytest")

    deps = _package_json_deps(root)
    if "vitest" in deps:
        found.runners.append("vitest")
    if "jest" in deps:
        found.unsupported.append("jest")
    elif (root / "package.json").is_file() and "vitest" not in deps:
        found.notes.append("package.json found without vitest; v0.1 supports vitest for JS/TS.")

    if (root / "go.mod").is_file():
        found.unsupported.append("go")
    if (root / "Cargo.toml").is_file():
        found.unsupported.append("cargo")
    return found
