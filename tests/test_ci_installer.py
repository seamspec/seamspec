"""The CI workflow and CODEOWNERS that `seamspec init` installs (SPEC §7.3, §16.5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app
from seamspec.core.config import load_config
from seamspec.installers import ci, scaffold

runner = CliRunner()


def _repo(tmp_path: Path, *files: str) -> Path:
    for name in files:
        (tmp_path / name).write_text('{"devDependencies": {"vitest": "3.2.7"}}' if name == "package.json" else "")
    scaffold.init(tmp_path, auto_run=True, claude_md=False, actor="Maya")
    return tmp_path


def test_workflow_is_safe_and_runs_doctor_then_verify(tmp_path: Path) -> None:
    root = _repo(tmp_path, "pyproject.toml", "uv.lock")
    text = ci.render_workflow(root, load_config(root))
    assert "pull_request_target" not in text.replace("Never switch to pull_request_target", "")
    assert "permissions:\n  contents: read" in text and "fetch-depth: 0" in text
    assert text.index("seamspec doctor --ci") < text.index("seamspec verify --all --ci")
    assert "uv sync --locked" in text and "{{" not in text


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (("pyproject.toml", "requirements.txt"), "uv pip install -r requirements.txt pytest"),
        (("pyproject.toml",), "uv pip install pytest"),
        (("package.json", "package-lock.json"), "npm ci"),
        (("package.json",), "npm install"),
    ],
)
def test_toolchain_follows_the_repo(tmp_path: Path, files: tuple[str, ...], expected: str) -> None:
    root = _repo(tmp_path, *files)
    assert expected in ci.render_workflow(root, load_config(root))


def test_yaml_parses(tmp_path: Path) -> None:
    yaml = pytest.importorskip("yaml")
    root = _repo(tmp_path, "pyproject.toml", "uv.lock", "package.json", "package-lock.json")
    doc = yaml.safe_load(ci.render_workflow(root, load_config(root)))
    runs = [s.get("run") for s in doc["jobs"]["verify"]["steps"]]
    assert "seamspec doctor --ci" in runs and doc["permissions"] == {"contents": "read"}


def test_existing_workflow_is_never_overwritten(tmp_path: Path) -> None:
    root = _repo(tmp_path, "pyproject.toml")
    path = root / ci.WORKFLOW_REL
    path.parent.mkdir(parents=True)
    path.write_text("mine\n")
    assert ci.install_workflow(root, load_config(root)) == "kept" and path.read_text() == "mine\n"


def test_codeowners_block_is_merged_not_clobbered(tmp_path: Path) -> None:
    root = _repo(tmp_path, "pyproject.toml", "package.json")
    path = root / ci.CODEOWNERS_REL
    path.parent.mkdir(parents=True)
    path.write_text("* @maya\n")
    cfg = load_config(root)
    assert ci.install_codeowners(root, cfg) == "updated"
    text = path.read_text()
    assert text.startswith("* @maya\n") and "/.seamspec/ @your-team/leads" in text
    assert "/tests/seamspec/ @your-team/leads" in text  # the vitest harness folder
    assert ci.install_codeowners(root, cfg) == "unchanged"
    assert text.count(ci.OWNERS_BEGIN) == 1


# --- through `seamspec init`, by mode --------------------------------------------------------------


def init(root: Path, *args: str, input: str = "") -> str:
    (root / "pyproject.toml").write_text("")
    result = runner.invoke(app, ["init", "--path", str(root), "--no-claude-md", "--no-plugin", *args], input)
    assert result.exit_code == 0, result.output
    return result.output


def test_enforced_without_terminal_or_flag_adds_nothing(tmp_path: Path) -> None:
    out = init(tmp_path, "--accept-auto-run")
    assert "seamspec init --ci" in out and not (tmp_path / ci.WORKFLOW_REL).exists()


def test_enforced_with_flag_adds_the_workflow_only(tmp_path: Path) -> None:
    init(tmp_path, "--accept-auto-run", "--ci")
    assert (tmp_path / ci.WORKFLOW_REL).is_file() and not (tmp_path / ci.CODEOWNERS_REL).exists()


@pytest.mark.parametrize("answer", ["y", "n"])
def test_enforced_in_a_terminal_asks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    out = init(tmp_path, input=f"y\n{answer}\n")  # auto-run consent, then the CI question
    assert "runs your approved rules on every PR" in out
    assert (tmp_path / ci.WORKFLOW_REL).exists() is (answer == "y")


def test_strict_always_adds_workflow_and_codeowners(tmp_path: Path) -> None:
    out = init(tmp_path, "--mode", "strict", "--accept-auto-run", "--no-ci")
    assert (tmp_path / ci.WORKFLOW_REL).is_file() and (tmp_path / ci.CODEOWNERS_REL).is_file()
    assert "--no-ci is ignored" in out


def test_advisory_never_adds_ci(tmp_path: Path) -> None:
    out = init(tmp_path, "--mode", "advisory", "--ci")
    assert "advisory mode never adds one" in out and not (tmp_path / ".github").exists()
