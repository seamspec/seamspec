"""SeamSpec's pytest.ini carries over the folders the project's own pytest settings add (ADR-20261018-0b7d).

Found in the capture calibration: a src/ project made importable by `pythonpath = ["src"]` in its
pytest settings. SeamSpec runs rule tests with its own pytest.ini, which dropped that, so every rule
test the agent proposed failed to import and nothing could be approved."""

from __future__ import annotations

from pathlib import Path

import pytest

from seamspec.core import doctor, lifecycle, runners
from seamspec.core.config import load_config
from seamspec.core.store import Store
from seamspec.installers import scaffold

TEST = "from jobqueue import Queue\n\n\ndef test_size():\n    assert Queue().size() == 0\n"
SRC_SETTINGS = '[project]\nname = "jobqueue"\n\n[tool.pytest.ini_options]\npythonpath = ["src"]\n'


def _project(root: Path, settings: dict[str, str]) -> Path:
    (root / "src/jobqueue").mkdir(parents=True)
    (root / "src/jobqueue/__init__.py").write_text("class Queue:\n    def size(self) -> int:\n        return 0\n")
    for name, text in settings.items():
        (root / name).write_text(text)
    (root / ".git").mkdir()
    return root


@pytest.mark.parametrize(
    "settings",
    [
        {"pyproject.toml": SRC_SETTINGS},
        {"pyproject.toml": '[project]\nname = "jobqueue"\n\n[tool.pytest.ini_options]\npythonpath = "src lib"\n'},
        {"pyproject.toml": '[project]\nname = "jobqueue"\n', "pytest.ini": "[pytest]\npythonpath = src\n"},
        {"pyproject.toml": '[project]\nname = "jobqueue"\n', "setup.cfg": "[tool:pytest]\npythonpath = src\n"},
    ],
)
def test_the_projects_pythonpath_is_read(tmp_path: Path, settings: dict[str, str]) -> None:
    root = _project(tmp_path, settings)
    assert runners.project_pythonpath(root) == ["src"]  # `lib` doesn't exist, so it's left out


def test_paths_outside_or_absolute_are_ignored(tmp_path: Path) -> None:
    settings = '[tool.pytest.ini_options]\npythonpath = [".", "../x", "/abs", "src"]\n'
    root = _project(tmp_path, {"pyproject.toml": settings})
    assert runners.project_pythonpath(root) == ["src"]


def test_init_carries_it_over_and_a_rule_test_imports_by_name(tmp_path: Path, monkeypatch) -> None:
    root = _project(tmp_path, {"pyproject.toml": SRC_SETTINGS})
    scaffold.init(root, auto_run=True, actor="Maya <maya@example.com>")
    assert "pythonpath = .. ../src" in (root / ".seamspec/pytest.ini").read_text()
    assert runners.seamspec_pythonpath(root) == [".", "src"]
    assert "adds src/, as your pytest settings do" in runners.import_hint(root, "pytest")
    assert not [f for f in doctor.run(root).findings if f.check == "pytest path"]

    store, cfg = Store(root), load_config(root)
    inv = lifecycle.propose_invariant(store, cfg, title="An empty queue has size zero",
                                      assertion="A new queue reports a size of zero.", scope_paths=["src/**"],
                                      runner="pytest", harness_code=TEST, origin_text="Agreed.")["id"]  # fmt: skip
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")
    lifecycle.approve(store, cfg, inv, actor="Maya <maya@example.com>")  # runs the test: it imports `jobqueue`


def test_doctor_warns_an_older_setup(tmp_path: Path) -> None:
    root = _project(tmp_path, {"pyproject.toml": SRC_SETTINGS})
    scaffold.init(root, auto_run=True, actor="Maya <maya@example.com>")
    ini = root / ".seamspec/pytest.ini"
    ini.write_text(ini.read_text().replace("pythonpath = .. ../src", "pythonpath = .."))  # as init wrote it before
    found = [f for f in doctor.run(root).findings if f.check == "pytest path"]
    assert found and "../src" in found[0].message and found[0].level == "warning"
    assert "installed in its virtualenv" in runners.import_hint(root, "pytest")


def test_a_project_without_pytest_settings_is_unchanged(tmp_path: Path) -> None:
    root = _project(tmp_path, {"pyproject.toml": '[project]\nname = "jobqueue"\n'})
    scaffold.init(root, auto_run=True, actor="Maya <maya@example.com>")
    text = (root / ".seamspec/pytest.ini").read_text()
    assert "pythonpath = ..\n" in text and "your own pytest settings" not in text
