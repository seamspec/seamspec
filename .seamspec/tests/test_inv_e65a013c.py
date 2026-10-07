"""Locked rule: the Stop check always finishes before Claude Code's Stop hook timeout, so its
decision is never discarded (ADR-20261005-5675)."""

import json
from pathlib import Path

import pytest

import seamspec
from seamspec.core.config import MAX_STOP_DEADLINE, ConfigError, parse_config

CHECKOUT = Path(seamspec.__file__).resolve().parents[1]


def test_stop_deadline_stays_below_the_hook_timeout() -> None:
    hooks = json.loads((CHECKOUT / "seamspec-plugin/hooks/hooks.json").read_text())["hooks"]
    timeout = hooks["Stop"][0]["hooks"][0]["timeout"]
    assert timeout - 30 >= MAX_STOP_DEADLINE  # time to start up, attribute and print
    assert parse_config(f"[verify]\nstop_deadline_seconds = {MAX_STOP_DEADLINE}\n")
    with pytest.raises(ConfigError):
        parse_config(f"[verify]\nstop_deadline_seconds = {MAX_STOP_DEADLINE + 1}\n")
