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


def test_rerunning_init_keeps_the_reviewers_someone_wrote(tmp_path: Path) -> None:
    """The block was rebuilt with the placeholder on every run, so a rerun of `init` (to add an editor,
    say) undid the guide's "replace @your-team/leads" step (catch-up review, #99)."""
    root = _repo(tmp_path, "pyproject.toml", "package.json")
    cfg = load_config(root)
    ci.install_codeowners(root, cfg)
    path = root / ci.CODEOWNERS_REL
    # A find-and-replace over the whole file, the marker line included.
    path.write_text(path.read_text().replace("@your-team/leads", "@acme/leads @maya"))
    assert ci.install_codeowners(root, cfg) == "updated"  # the marker line gets its own words back
    assert ci.install_codeowners(root, cfg) == "unchanged"
    text = path.read_text()
    assert text.count(ci.OWNERS_BEGIN) == 1 and text.count("# seamspec:begin") == 1
    assert "/.seamspec/ @acme/leads @maya" in text and "/tests/seamspec/ @acme/leads @maya" in text

    # A folder missing from the block (a runner added later) gets the owners of the block's first line.
    path.write_text(text.replace("/tests/seamspec/ @acme/leads @maya\n", ""))
    assert ci.install_codeowners(root, cfg) == "updated"
    assert "/tests/seamspec/ @acme/leads @maya" in path.read_text()


def test_reviewers_after_a_tab_are_kept_and_the_hint_goes(tmp_path: Path) -> None:
    """CODEOWNERS allows a tab between the folder and its owners; they were read as missing and replaced
    with the placeholder. The hint only reads owner entries, not the marker's comment (#103)."""
    root = _repo(tmp_path, "pyproject.toml")
    cfg = load_config(root)
    ci.install_codeowners(root, cfg)
    path = root / ci.CODEOWNERS_REL
    assert ci.placeholder_left(path.read_text())
    path.write_text(path.read_text().replace("/.seamspec/ @your-team/leads", "/.seamspec/\t@maya  @acme/leads"))
    ci.install_codeowners(root, cfg)
    assert "/.seamspec/ @maya @acme/leads" in path.read_text()
    assert not ci.placeholder_left(path.read_text()) and ci.PLACEHOLDER_OWNER in path.read_text()  # the comment
    assert "replace @your-team/leads" not in init(root, "--mode", "strict")


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


@pytest.fixture
def released_build(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pretend this SeamSpec is a published version (the checkout is a development build)."""
    monkeypatch.setattr(ci, "__version__", "0.1.0")
    return "0.1.0"


@pytest.fixture
def unreleased_build(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin a development version, so these tests don't depend on what the checkout's version is today
    (Copilot, #51): they must still cover this branch after the first release bumps the version."""
    monkeypatch.setattr(ci, "__version__", "0.2.0.dev0")
    return "0.2.0.dev0"


@pytest.mark.parametrize("answer", ["y", "n"])
def test_enforced_in_a_terminal_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, released_build: str, answer: str
) -> None:
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


# --- how the workflow gets SeamSpec (dogfooding finding #1, ADR-20261011-a9f3) ---------------------


@pytest.mark.parametrize(
    ("version", "is_release"),
    [("0.1.0", True), ("1.2.3", True), ("0.1.0rc1", True), ("0.2.0b2", True), ("1.0.0.post1", True),
     ("0.1.0.dev0", False), ("0.1.0+local", False), ("0.2.0a1.dev3", False), ("", False)],
)  # fmt: skip
def test_which_versions_count_as_released(version: str, is_release: bool) -> None:
    assert ci.released(version) is is_release


def test_a_release_pins_the_version_that_wrote_the_workflow(tmp_path: Path, released_build: str) -> None:
    root = _repo(tmp_path, "pyproject.toml", "uv.lock")
    text = ci.render_workflow(root, load_config(root))
    assert '      - run: uv tool install "seamspec==0.1.0"\n' in text and "git+" not in text
    assert text.index("uv tool install") < text.index("uv sync --locked") < text.index("seamspec doctor --ci")


def test_an_unreleased_build_installs_from_the_repository_and_says_so(tmp_path: Path, unreleased_build: str) -> None:
    """`uv tool install seamspec` would fetch whatever is on PyPI under that name, not this build."""
    assert not ci.released()
    root = _repo(tmp_path, "pyproject.toml", "uv.lock")
    text = ci.render_workflow(root, load_config(root))
    assert f'      - run: uv tool install "git+{ci.REPOSITORY}@main"\n' in text
    assert "which your CI must be able to read" in text
    runs = [line.strip() for line in text.splitlines() if line.strip().startswith("- run:")]
    assert "- run: uv tool install seamspec" not in runs and len([r for r in runs if "uv tool install" in r]) == 1


def test_both_install_steps_are_valid_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml = pytest.importorskip("yaml")
    root = _repo(tmp_path, "pyproject.toml", "uv.lock")
    for version in ("0.1.0.dev0", "0.1.0"):
        monkeypatch.setattr(ci, "__version__", version)
        doc = yaml.safe_load(ci.render_workflow(root, load_config(root)))
        runs = [s.get("run", "") for s in doc["jobs"]["verify"]["steps"]]
        assert sum("uv tool install" in r for r in runs) == 1 and "seamspec doctor --ci" in runs


def test_an_unreleased_build_does_not_offer_the_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unreleased_build: str
) -> None:
    """In a terminal, enforced mode used to ask. A workflow that can't install SeamSpec isn't worth offering."""
    monkeypatch.setattr("seamspec.cli._interactive", lambda: True)
    out = init(tmp_path, input="y\n")  # the auto-run consent only: no CI question follows
    assert "CI workflow: not offered yet" in out and "seamspec init --ci" in out
    assert "runs your approved rules on every PR" not in out and not (tmp_path / ci.WORKFLOW_REL).exists()


@pytest.mark.parametrize("args", [("--accept-auto-run", "--ci"), ("--mode", "strict", "--accept-auto-run")])
def test_an_unreleased_build_still_writes_it_when_asked_and_explains(
    tmp_path: Path, unreleased_build: str, args: tuple[str, ...]
) -> None:
    out = init(tmp_path, *args)
    assert (tmp_path / ci.WORKFLOW_REL).is_file()
    assert "your CI must be able to read that repository" in out and ci.REPOSITORY in out


def test_a_release_writes_it_without_the_note(tmp_path: Path, released_build: str) -> None:
    out = init(tmp_path, "--accept-auto-run", "--ci")
    assert (tmp_path / ci.WORKFLOW_REL).is_file() and "must be able to read" not in out
