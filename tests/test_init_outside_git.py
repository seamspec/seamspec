"""`init` asks before setting up a folder that isn't a git repository (ADR-20261105-5c1d).

Found on SessionWalk: `seamspec init --hosts antigravity` was run from the folder that holds the owner's
projects, not from SessionWalk. It set that folder up (config, CLAUDE.md, AGENTS.md, a CI workflow, the
plugin) and only then noted "not a git repository".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.cli import app

runner = CliRunner()


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)


def projects_folder(tmp_path: Path) -> Path:
    """A folder holding two git projects, like ~/Documents."""
    root = tmp_path / "Documents"
    for name in ("sessionwalk", "seamspec"):
        (root / name).mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(root / name)], check=True)
    return root


def init(root: Path, *args: str, input: str = ""):
    return runner.invoke(app, ["init", "--path", str(root), "--no-plugin", "--no-ci", *args], input)


def written(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.name not in ("sessionwalk", "seamspec"))


def test_in_a_terminal_it_asks_first_and_writes_nothing_on_no(tmp_path: Path, terminal: None) -> None:
    root = projects_folder(tmp_path)
    out = init(root, input="\n")  # Enter: the default is no
    assert out.exit_code == 1
    assert f"{root} isn't a git repository." in out.output
    assert "It holds other projects (seamspec, sessionwalk): did you mean to run this inside one of them?" in out.output
    assert "Set SeamSpec up here anyway? [y/N]" in out.output and "nothing was written" in out.output
    assert written(root) == []


def test_a_yes_sets_it_up_as_before(tmp_path: Path, terminal: None) -> None:
    root = tmp_path / "scratch"
    root.mkdir()
    out = init(root, input="y\ny\n")  # set up here anyway, then the auto-run consent
    assert out.exit_code == 0, out.output
    assert "isn't a git repository" in out.output and "It holds other projects" not in out.output
    assert (root / ".seamspec/config.toml").is_file()


def test_without_a_terminal_a_folder_of_projects_is_refused(tmp_path: Path) -> None:
    root = projects_folder(tmp_path)
    out = init(root)
    assert out.exit_code == 1 and "Nothing was written. Run it in the project's folder" in out.output
    assert written(root) == []


def test_without_a_terminal_a_plain_folder_is_still_set_up(tmp_path: Path) -> None:
    """Scripted setups (and a project that isn't in git yet) keep working, with the note as before."""
    out = init(tmp_path)
    assert out.exit_code == 0, out.output
    assert "not a git repository" in out.output and (tmp_path / ".seamspec/config.toml").is_file()


def test_a_git_repository_or_a_folder_inside_one_is_not_asked(tmp_path: Path, terminal: None) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    sub = tmp_path / "services" / "api"
    sub.mkdir(parents=True)
    for root in (tmp_path, sub):
        out = init(root, input="y\n")  # the auto-run consent only
        assert out.exit_code == 0, out.output
        assert "isn't a git repository" not in out.output


def test_a_folder_already_set_up_is_not_asked_again(tmp_path: Path, terminal: None) -> None:
    root = tmp_path / "scratch"
    root.mkdir()
    assert init(root, input="y\ny\n").exit_code == 0
    again = init(root, input="\n")
    assert again.exit_code == 0, again.output
    assert "Set SeamSpec up here anyway?" not in again.output


def test_folder_names_are_quoted_so_they_cannot_repaint_the_question(tmp_path: Path, terminal: None) -> None:
    """Copilot on #116: a folder name with a newline or terminal escapes could hide the warning."""
    root = tmp_path / "Documents"
    sneaky = root / "proj\x1b[2J\nAll good"
    sneaky.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(sneaky)], check=True)
    out = init(root, input="\n")
    assert "\x1b[2J" not in out.output and '"proj\\u001b[2J\\nAll good"' in out.output


def test_a_broken_config_outside_git_gets_its_error_not_the_question(tmp_path: Path, terminal: None) -> None:
    """Copilot on #116: a folder already set up, with a config that doesn't load, isn't a new setup."""
    root = projects_folder(tmp_path)
    (root / ".seamspec").mkdir()
    (root / ".seamspec/config.toml").write_text("mode = [broken\n")
    out = init(root, input="\n")
    assert "Set SeamSpec up here anyway?" not in out.output
    assert "isn't a git repository" not in out.output
