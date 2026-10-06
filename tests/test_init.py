from __future__ import annotations

from pathlib import Path

import pytest

from seamspec.core.config import load_config
from seamspec.core.runners import detect
from seamspec.installers import directive, scaffold
from seamspec.installers.directive import BEGIN, END, DirectiveError


def test_init_scaffolds_python_repo(repo: Path) -> None:
    for d in ("invariants", "dead_ends", "adrs", "proposed", "retired", ".local", "tests"):
        assert (repo / ".seamspec" / d).is_dir()
    assert "pythonpath = ..\n" in (repo / ".seamspec/pytest.ini").read_text()
    assert not (repo / ".seamspec/vitest.config.mjs").exists()
    assert ".seamspec/.local/" in (repo / ".gitignore").read_text()
    cfg = load_config(repo)
    assert list(cfg.runners) == ["pytest"] and cfg.mode == "enforced"


def test_init_is_idempotent_and_never_clobbers(repo: Path) -> None:
    config = repo / ".seamspec/config.toml"
    config.write_text(config.read_text().replace("max_pending = 10", "max_pending = 4"))
    before = {p: p.read_bytes() for p in (config, repo / ".gitignore", repo / "CLAUDE.md")}
    report = scaffold.init(repo)
    assert {p: p.read_bytes() for p in before} == before
    assert dict(report.actions)[".seamspec/config.toml"] == "kept"
    assert dict(report.actions)["CLAUDE.md"] == "unchanged"
    assert load_config(repo).proposals.max_pending == 4


def test_init_typescript_repo(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"devDependencies": {"vitest": "^2.0.0"}}')
    scaffold.init(tmp_path)
    assert list(load_config(tmp_path).runners) == ["vitest"]
    assert (tmp_path / "tests/seamspec").is_dir()
    assert "tests/seamspec/inv_*.test.ts" in (tmp_path / ".seamspec/vitest.config.mjs").read_text()


def test_init_without_known_language(tmp_path: Path) -> None:
    report = scaffold.init(tmp_path)
    assert load_config(tmp_path).runners == {}
    assert report.detection.runners == []


def test_init_strict_mode(tmp_path: Path) -> None:
    scaffold.init(tmp_path, mode="strict", auto_run=True)
    cfg = load_config(tmp_path)
    assert cfg.mode == "strict" and cfg.hooks.fail_closed is True


@pytest.mark.parametrize("mode", ["enforced", "strict"])
def test_no_consent_falls_back_to_advisory(tmp_path: Path, mode: str) -> None:
    report = scaffold.init(tmp_path, mode=mode, auto_run=False)
    assert report.mode == "advisory" and load_config(tmp_path).mode == "advisory"
    assert report.consent is False and report.hook is None


def test_gitignore_merge_keeps_existing(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("node_modules/")  # no trailing newline
    scaffold.init(tmp_path)
    text = (tmp_path / ".gitignore").read_text()
    assert text.startswith("node_modules/\n") and text.endswith(".seamspec/.local/\n.seamspec/**/__pycache__/\n")


@pytest.mark.parametrize(
    "files,runners,unsupported",
    [
        ({"setup.py": ""}, ["pytest"], []),
        ({"requirements-dev.txt": ""}, ["pytest"], []),
        ({"package.json": '{"dependencies": {"jest": "1"}}'}, [], ["jest"]),
        ({"go.mod": "module x"}, [], ["go"]),
        ({"Cargo.toml": ""}, [], ["cargo"]),
        ({"pyproject.toml": "", "package.json": '{"devDependencies": {"vitest": "1"}}'}, ["pytest", "vitest"], []),
        ({"package.json": "not json"}, [], []),
    ],
)
def test_detection(tmp_path: Path, files: dict[str, str], runners: list[str], unsupported: list[str]) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    found = detect(tmp_path)
    assert found.runners == runners and found.unsupported == unsupported


# --- CLAUDE.md directive block (SPEC §18, ADR-20261005-c41d) ---


def test_merge_into_empty_and_missing() -> None:
    assert directive.merge("") == directive.render_block() + "\n"


def test_merge_appends_and_preserves_user_content() -> None:
    user = "# My project\n\nBe concise.\n"
    out = directive.merge(user)
    assert out.startswith(user + "\n" + BEGIN)
    assert out.endswith(END + "\n")


def test_merge_replaces_block_in_place() -> None:
    old = f"# Top\n\n{BEGIN}\nold rules\n{END}\n\n## After\nkeep me\n"
    out = directive.merge(old)
    assert "old rules" not in out
    assert out.startswith("# Top\n\n" + BEGIN)
    assert out.endswith(f"{END}\n\n## After\nkeep me\n")
    assert directive.merge(out) == out


def test_merge_accepts_edited_begin_marker() -> None:
    old = "<!-- seamspec:begin anything -->\nx\n<!-- seamspec:end -->\n"
    assert directive.merge(old) == directive.render_block() + "\n"


@pytest.mark.parametrize(
    "bad",
    [
        f"{BEGIN}\nno end\n",
        f"{END}\n{BEGIN}\n",
        f"{BEGIN}\n{END}\n{BEGIN}\n{END}\n",
    ],
)
def test_merge_refuses_broken_markers(bad: str) -> None:
    with pytest.raises(DirectiveError):
        directive.merge(bad)


def test_install_and_drift(tmp_path: Path) -> None:
    assert directive.drift(tmp_path)
    assert directive.install(tmp_path) == "created"
    assert not directive.drift(tmp_path)
    assert directive.install(tmp_path) == "unchanged"
    path = tmp_path / "CLAUDE.md"
    path.write_text(path.read_text().replace("Only humans approve", "Agents approve"))
    assert directive.drift(tmp_path)
    assert directive.install(tmp_path) == "updated"


def test_v01_directive_leaves_out_v02_rules() -> None:
    text = directive.directive_text()
    assert "braindump" not in text.lower()
    assert "get_constraints" in text and "seamspec review" in text


def test_init_without_claude_md(tmp_path: Path) -> None:
    scaffold.init(tmp_path, claude_md=False)
    assert not (tmp_path / "CLAUDE.md").exists()


def test_consent_later_turns_automatic_runs_on(tmp_path: Path) -> None:
    """Declining at first, then re-running init with consent, must switch out of advisory mode."""
    (tmp_path / "pyproject.toml").write_text("")
    scaffold.init(tmp_path, auto_run=False)
    assert load_config(tmp_path).mode == "advisory"
    before = (tmp_path / ".seamspec/config.toml").read_text()
    report = scaffold.init(tmp_path, mode="strict", auto_run=True)
    after = (tmp_path / ".seamspec/config.toml").read_text()
    assert report.mode == "strict" and load_config(tmp_path).mode == "strict"
    assert dict(report.actions)[".seamspec/config.toml"] == "updated (mode: strict)"
    cfg = load_config(tmp_path)
    assert cfg.hooks.fail_closed is True and cfg.execution.trust_level == "harness"  # strict defaults restored
    assert "[runners.pytest]" in after and after.count("\n") == before.count("\n")  # nothing else moved


def test_gitignore_keeps_bytecode_out_of_the_ledger(tmp_path: Path) -> None:
    """Finding #6: pytest runs of rule tests write __pycache__ into .seamspec/tests/."""
    import subprocess

    scaffold.init(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    cache = tmp_path / ".seamspec/tests/__pycache__"
    cache.mkdir(parents=True)
    (cache / "test_inv_00000001.cpython-312-pytest-9.1.1.pyc").write_bytes(b"x")
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=tmp_path,
                         capture_output=True, text=True).stdout  # fmt: skip
    assert "__pycache__" not in out
