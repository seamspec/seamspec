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


# --- hints for agents writing rule tests (§12A.6, ADR-20261011-e7c5) ---------------------------------

NOT_PACKAGES = {"tests", "test", "docs", "doc", "examples", "scripts", "build", "dist", "node_modules"}


def _packages(folder: Path) -> list[str]:
    """Importable packages directly inside `folder`: sub-folders with an __init__.py."""
    if not folder.is_dir():
        return []
    return sorted(
        d.name
        for d in folder.iterdir()
        if d.is_dir() and d.name.isidentifier() and d.name not in NOT_PACKAGES and (d / "__init__.py").is_file()
    )


def _project_name(root: Path) -> str | None:
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = data.get("project", {}).get("name") if isinstance(data.get("project"), dict) else None
    return name.replace("-", "_").replace(".", "_").lower() if isinstance(name, str) else None


def python_layout(root: Path) -> tuple[str, str | None]:
    """How this project's Python code is imported, and one package to use as an example:
    - ("src-package", None): `src/` is itself a package (`from src.queue import ...`);
    - ("src", pkg): packages live under `src/` and are imported by name once the project is installed;
    - ("flat", pkg): packages sit at the repository root;
    - ("flat", None): nothing recognisable yet."""
    if (root / "src" / "__init__.py").is_file():
        return "src-package", None
    preferred = _project_name(root)
    for kind, folder in (("src", root / "src"), ("flat", root)):
        found = _packages(folder)
        if found:
            return kind, preferred if preferred in found else found[0]
    return "flat", None


def project_pythonpath(root: Path) -> list[str]:
    """Folders the project's own pytest settings put on sys.path (`pythonpath` in pyproject.toml's
    `[tool.pytest.ini_options]`, pytest.ini, setup.cfg's `[tool:pytest]` or tox.ini's `[pytest]`):
    relative, inside the repository, existing, and not the root itself. SeamSpec's own pytest.ini
    replaces the project's settings, so it has to carry these over (ADR-20261018-0b7d)."""
    import configparser
    import tomllib

    raw: list[str] = []
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        value = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("pythonpath")
        raw += value if isinstance(value, list) else str(value or "").split()
    except (OSError, ValueError):
        pass
    for name, section in (("pytest.ini", "pytest"), ("setup.cfg", "tool:pytest"), ("tox.ini", "pytest")):
        parser = configparser.ConfigParser()
        try:
            parser.read(root / name, encoding="utf-8")
        except (OSError, configparser.Error):
            continue
        if parser.has_option(section, "pythonpath"):
            raw += parser.get(section, "pythonpath").split()
    out: list[str] = []
    for entry in raw:
        rel = Path(str(entry).strip())
        if not str(rel) or rel.is_absolute() or ".." in rel.parts or str(rel) in (".", ""):
            continue
        if (root / rel).is_dir() and rel.as_posix() not in out:
            out.append(rel.as_posix())
    return out


def seamspec_pythonpath(root: Path) -> list[str]:
    """What `.seamspec/pytest.ini` puts on sys.path, relative to the repository root."""
    import configparser

    parser = configparser.ConfigParser()
    try:
        parser.read(root / ".seamspec" / "pytest.ini", encoding="utf-8")
    except (OSError, configparser.Error):
        return []
    if not parser.has_option("pytest", "pythonpath"):
        return []
    out = []
    for entry in parser.get("pytest", "pythonpath").split():
        rel = Path(entry)
        if rel.parts[:1] == ("..",):
            out.append(Path(*rel.parts[1:]).as_posix() if len(rel.parts) > 1 else ".")
    return out


def import_hint(root: Path, runner: str) -> str | None:
    """How a rule test for this runner imports the project's code."""
    if runner == "vitest":
        return (
            "Import project code with paths relative to tests/seamspec/, e.g. `../../src/queue`; "
            "SeamSpec's own vitest config applies, not the project's setupFiles or aliases."
        )
    if runner != "pytest":
        return None
    kind, package = python_layout(root)
    tail = "SeamSpec's own pytest.ini puts the root on sys.path and ignores conftest.py files."
    if kind == "src-package":
        return f"Import project code from the repo root, e.g. `from src.queue import backoff_delay`; {tail}"
    if kind == "src":
        how = (
            "It is importable because SeamSpec's own pytest.ini adds src/, as your pytest settings do."
            if "src" in seamspec_pythonpath(root)
            else "It is importable because the project is installed in its virtualenv (`uv sync`, "
            "`pip install -e .`); if the import fails, install it first."
        )
        return (
            f"This project keeps its package under src/: import it by name, e.g. `from {package} import ...`, "
            f"never `src.{package}` (that would load a second copy of the code). {how} "
            "SeamSpec's own pytest.ini ignores conftest.py files."
        )
    if package:
        return f"Import project code from the repo root, e.g. `from {package} import ...`; {tail}"
    return f"Import project code from the repo root, or by package name if the project is installed; {tail}"
