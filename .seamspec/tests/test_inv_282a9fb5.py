"""Rule: re-running `seamspec init` never removes a line it didn't write from CLAUDE.md, wherever
the line sits, inside SeamSpec's marked block included (ADR-20261011-b1c8)."""

from pathlib import Path

from seamspec.installers import directive

MINE = ["Commit straight to main.", "  - never force-push", "Ask before adding a dependency."]


def test_lines_written_inside_the_block_survive_a_rerun(tmp_path: Path) -> None:
    directive.install(tmp_path)
    path = tmp_path / "CLAUDE.md"
    block = path.read_text().splitlines()
    block[1:1] = [MINE[0]]  # right after the begin marker
    block[len(block) // 2 : len(block) // 2] = [MINE[1]]  # in the middle of SeamSpec's text
    block[-1:-1] = [MINE[2]]  # just before the end marker
    path.write_text("# My project\n\nabove\n" + "\n".join(block) + "\n\nbelow\n")

    status, kept = directive.install_keeping(tmp_path)

    text = path.read_text()
    assert status == "updated" and kept == MINE
    assert all(text.count(line) == 1 for line in MINE)
    assert text.startswith("# My project\n\nabove\n") and text.endswith("\n\nbelow\n")
    assert not directive.drift(tmp_path)  # the block is SeamSpec's own text again
    assert directive.install_keeping(tmp_path) == ("unchanged", [])


def test_seamspecs_own_older_wording_is_not_mistaken_for_someone_elses(tmp_path: Path) -> None:
    older = "6. Only humans approve invariants. Remind the user to run `seamspec review` when proposals are pending."
    (tmp_path / "CLAUDE.md").write_text(f"{directive.BEGIN}\n# SeamSpec Protocol\n{older}\n{directive.END}\n")
    status, kept = directive.install_keeping(tmp_path)
    assert status == "updated" and kept == []
    assert older not in (tmp_path / "CLAUDE.md").read_text()
