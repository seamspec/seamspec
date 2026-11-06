"""Agents are told when to record a decision (ADR-20261105-7a4e).

SessionWalk dogfooding: `.seamspec/adrs/` stayed empty across four milestones, because `propose_decision`
was only mentioned in the drain command. The protocol block, the checkpoint and the CLI fallback now say
when to use it: a settled design choice that shapes future work on some files, which is neither a test
(propose_invariant) nor a failed attempt (log_dead_end).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from seamspec.core import commands
from seamspec.installers import directive

PLUGIN = Path(__file__).resolve().parents[1] / "seamspec-plugin"


def flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("target", ["claude", "agents"])
def test_the_protocol_says_when_to_propose_a_decision(target: str) -> None:
    text = flat(directive.directive_text() if target == "claude" else directive.directive_text("agents"))
    assert "call `propose_decision` scoped to those files, so `get_constraints` shows it in later sessions" in text
    assert "a rationale or trade-off rather than something a test can check or a failed attempt" in text
    assert "deferring a feature after measuring it, choosing an algorithm or a data representation" in text


@pytest.mark.parametrize("host", ["claude", *commands.OTHER_HOSTS])
def test_the_checkpoint_records_decisions_and_the_fallback_names_the_command(host: str) -> None:
    if host == "claude":
        checkpoint = (PLUGIN / "skills/checkpoint/SKILL.md").read_text()
        others = [p.read_text() for p in (PLUGIN / "skills").glob("*/SKILL.md")]
    else:
        checkpoint = commands.render("checkpoint", host)
        others = [commands.render(name, host) for name in commands.commands_for(host)]
    assert "6. Record design choices settled this session" in checkpoint
    assert "with `propose_decision`, scoped to those files" in flat(checkpoint)
    with_footer = [t for t in others if "Rules for every SeamSpec command" in t]  # not VS Code's reviewer prompt
    assert len(with_footer) >= len(others) - 1
    for text in with_footer:  # the shared rules, including the CLI fallback
        assert "`seamspec propose-decision --json -`" in flat(text)
