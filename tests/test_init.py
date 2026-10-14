from __future__ import annotations

import subprocess
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
    assert text.startswith("node_modules/\n") and ".seamspec/.local/\n.seamspec/**/__pycache__/\n" in text
    assert text.endswith("\nBRAINDUMP.md\n")  # created git-ignored with the scratchpad (ADR-20261013-d9e4)


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


# Rule 6 as the first version of the block worded it: SeamSpec's own line, though no longer in the template.
OLD_RULE_6 = "6. Only humans approve invariants. Remind the user to run `seamspec review` when proposals are pending."


def test_merge_into_empty_and_missing() -> None:
    assert directive.merge("") == directive.render_block() + "\n"


def test_merge_appends_and_preserves_user_content() -> None:
    user = "# My project\n\nBe concise.\n"
    out = directive.merge(user)
    assert out.startswith(user + "\n" + BEGIN)
    assert out.endswith(END + "\n")


def test_merge_replaces_block_in_place() -> None:
    old = f"# Top\n\n{BEGIN}\n{OLD_RULE_6}\n{END}\n\n## After\nkeep me\n"
    out = directive.merge(old)
    assert OLD_RULE_6 not in out
    assert out.startswith("# Top\n\n" + BEGIN)
    assert out.endswith(f"{END}\n\n## After\nkeep me\n")
    assert directive.merge(out) == out


def test_merge_accepts_edited_begin_marker() -> None:
    old = f"<!-- seamspec:begin anything -->\n{OLD_RULE_6}\n<!-- seamspec:end -->\n"
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


# --- lines someone else wrote inside the block are kept (dogfooding #8, ADR-20261011-b1c8) ---

SOLO = "This is a solo project: commit directly to `main`; don't create feature branches."


def test_a_line_written_inside_the_block_is_kept_above_it() -> None:
    """The specagent case: an agent put the owner's instruction right after the begin marker."""
    old = directive.render_block().replace(BEGIN, f"{BEGIN}\n{SOLO}\n") + "\n"
    out, kept = directive.merge_keeping(old)
    assert kept == [SOLO]
    assert out == f"{SOLO}\n\n{directive.render_block()}\n"
    assert directive.merge_keeping(out) == (out, [])  # nothing left to move the second time


def test_kept_lines_keep_their_order_and_the_text_around_the_block() -> None:
    body = directive.directive_text().splitlines()
    inner = "\n".join(["first of mine", *body[:5], "", "  - second of mine", *body[5:], "third of mine"])
    old = f"# Top\n\nintro\n{BEGIN}\n{inner}\n{END}\n\n## After\nkeep me\n"
    out, kept = directive.merge_keeping(old)
    assert kept == ["first of mine", "  - second of mine", "third of mine"]
    assert out == (
        "# Top\n\nintro\n\nfirst of mine\n  - second of mine\nthird of mine\n\n"
        f"{directive.render_block()}\n\n## After\nkeep me\n"
    )


def test_upgrading_from_older_wording_keeps_nothing() -> None:
    """SeamSpec's own earlier lines are recognised, so an ordinary upgrade moves nothing out of the block."""
    assert OLD_RULE_6 not in directive.directive_text()
    old = f"{BEGIN}\n# SeamSpec Protocol\n\n   {OLD_RULE_6}  \n{END}\n"  # indentation doesn't matter
    assert directive.foreign_lines(old) == []
    out, kept = directive.merge_keeping(old)
    assert kept == [] and out == directive.render_block() + "\n"


def test_known_lines_file_covers_the_current_template() -> None:
    """After editing directive.md, run `uv run python -m seamspec.installers.directive`: the next wording
    change must still recognise today's lines as SeamSpec's."""
    from importlib.resources import files

    recorded = set(files("seamspec.templates").joinpath(directive.KNOWN_LINES).read_text("utf-8").split())
    current = {directive._key(ln) for ln in directive.directive_text().splitlines() if ln.strip()}
    assert current <= recorded


def test_init_reports_the_lines_it_kept(tmp_path: Path) -> None:
    scaffold.init(tmp_path)
    path = tmp_path / "CLAUDE.md"
    path.write_text(path.read_text().replace(BEGIN, f"{BEGIN}\n{SOLO}"))
    assert directive.foreign_in(tmp_path) == [SOLO]
    report = scaffold.init(tmp_path)
    assert report.kept_lines == [SOLO] and dict(report.actions)["CLAUDE.md"] == "updated"
    assert path.read_text().startswith(f"{SOLO}\n\n{BEGIN}\n# SeamSpec Protocol")
    assert directive.foreign_in(tmp_path) == [] and not directive.drift(tmp_path)
    assert scaffold.init(tmp_path).kept_lines == []


def test_v01_directive_covers_braindump_and_still_the_projects_list() -> None:
    """BRAINDUMP moved into v0.1 (ADR-20261013-f4a8, ADR-20261013-d9e4); a plan's list still works."""
    text = directive.directive_text()
    assert "Never edit it" in text and "/seamspec:drain" in text and '"sort my braindump" → drain' in text
    assert "don't sort without a yes" in text
    assert "get_constraints" in text and "seamspec review" in text
    assert "list of rules it intends to lock" in text  # a plan section works today, without BRAINDUMP


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
    assert dict(report.actions)[".seamspec/config.toml"] == "updated (mode: advisory → strict)"
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


def test_local_state_is_ignored_even_without_the_root_gitignore(tmp_path: Path) -> None:
    """Dogfooding #8: on a branch whose .gitignore predates SeamSpec, local state must stay invisible to git."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    scaffold.init(tmp_path, auto_run=True, actor="Maya")
    (tmp_path / ".gitignore").unlink()
    assert (tmp_path / ".seamspec/.local/.gitignore").read_text().splitlines()[-1] == "*"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".seamspec/.local/consent.json"], cwd=tmp_path, capture_output=True
    )
    assert ignored.returncode == 0


# --- switching modes later (§7.3, ADR-20261007-1b4c) -----------------------------------------------


def test_rerunning_init_without_a_mode_keeps_the_current_one(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    scaffold.init(tmp_path, mode="strict", auto_run=True)
    scaffold.init(tmp_path, auto_run=True)  # no mode: must not fall back to "enforced"
    assert load_config(tmp_path).mode == "strict"


def test_strict_and_back_only_touches_lines_init_wrote(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    scaffold.init(tmp_path, auto_run=True)
    original = (tmp_path / ".seamspec/config.toml").read_text()
    scaffold.init(tmp_path, mode="strict", auto_run=True)
    cfg = load_config(tmp_path)
    assert cfg.mode == "strict" and cfg.hooks.fail_closed and cfg.execution.trust_level == "harness"
    assert cfg.review.chat_approvals is False
    scaffold.init(tmp_path, mode="enforced", auto_run=True)
    assert (tmp_path / ".seamspec/config.toml").read_text() == original  # exactly as before
    # a value a human edited is left alone
    path = tmp_path / ".seamspec/config.toml"
    path.write_text(path.read_text().replace(scaffold.NON_STRICT_HOOKS, "fail_closed = true\n"))
    scaffold.init(tmp_path, mode="strict", auto_run=True)
    scaffold.init(tmp_path, mode="enforced", auto_run=True)
    assert load_config(tmp_path).hooks.fail_closed is True


def test_raising_the_mode_needs_automatic_runs(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    scaffold.init(tmp_path, auto_run=True)
    report = scaffold.init(tmp_path, mode="strict", auto_run=False)
    assert load_config(tmp_path).mode == "enforced"
    assert dict(report.actions)[".seamspec/config.toml"].startswith("kept (mode: enforced; strict needs")


def test_advisory_removes_seamspecs_hook_but_never_someone_elses(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "pyproject.toml").write_text("")
    scaffold.init(tmp_path, auto_run=True)
    hook = tmp_path / ".git/hooks/pre-commit"
    assert hook.is_file()
    report = scaffold.init(tmp_path, mode="advisory")
    assert not hook.exists() and report.hook is not None and report.hook.status == "removed"
    hook.write_text("#!/bin/sh\necho mine\n")
    scaffold.init(tmp_path, mode="advisory")
    assert hook.read_text() == "#!/bin/sh\necho mine\n"


def test_lowering_through_the_api_never_needs_consent(tmp_path: Path) -> None:
    """scaffold.init: strict → enforced without auto_run is a lowering, not a raise."""
    (tmp_path / "pyproject.toml").write_text("")
    scaffold.init(tmp_path, mode="strict", auto_run=True)
    report = scaffold.init(tmp_path, mode="enforced", auto_run=False)
    assert load_config(tmp_path).mode == "enforced"
    assert dict(report.actions)[".seamspec/config.toml"] == "updated (mode: strict → enforced)"
