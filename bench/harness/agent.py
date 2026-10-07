"""Drive the agent: one fresh Claude Code session per scripted session, prompts resumed within it.

Every condition gets the same prompts, model, tools and settings. User-level settings are
excluded (`--setting-sources project,local`) so the owner's own plugins and hooks can't change the
results.

Billing is the owner's choice (ADR-20261006-c8b9): `plan` removes ANTHROPIC_API_KEY so Claude Code
uses its own login (the Pro plan); `api` requires the key in the environment. Either way, the
`apiKeySource` Claude Code reports at the start of every prompt is checked, and a mismatch stops
the batch before it bills the wrong account.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "seamspec-plugin"
PROMPT_TIMEOUT = 1500  # seconds per prompt, including Stop-hook retries

MCP_TOOLS = [
    f"mcp__plugin_seamspec_seamspec__{name}"
    for name in ("get_constraints", "propose_invariant", "log_dead_end", "request_supersede", "verify")
]
ALLOWED_TOOLS = [
    "Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "TodoWrite",
    "Bash(.venv/bin/python -m pytest:*)", "Bash(.venv/bin/pytest:*)", "Bash(python -m pytest:*)",
    "Bash(python3 -m pytest:*)", "Bash(pytest:*)",
    "Bash(npx vitest:*)", "Bash(npm test:*)", "Bash(npm run test:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(git add:*)", "Bash(git commit:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(seamspec:*)",
    *MCP_TOOLS,
]  # fmt: skip


BILLING = ("plan", "api")


class StopBatch(RuntimeError):
    """Something that makes every remaining run pointless or unsafe: stop the whole batch."""


class BillingMismatch(StopBatch):
    """Claude Code would bill a different account than the owner chose."""


class AuthFailed(StopBatch):
    """Claude Code can't authenticate (e.g. an invalid API key): every further prompt would only retry and fail."""


@dataclass
class PromptResult:
    session: int
    prompt: int
    cost_usd: float = 0.0
    turns: int = 0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    is_error: bool = False
    note: str = ""
    session_id: str | None = None
    api_key_source: str | None = None


@dataclass
class SessionLog:
    results: list[PromptResult] = field(default_factory=list)


def parse_stream(lines: list[str]) -> dict:
    """The final `result` event of a `--output-format stream-json` run (empty if none)."""
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            return event
    return {}


def api_key_source(lines: list[str]) -> str | None:
    """`apiKeySource` from the stream's `system` init event: how Claude Code is billed."""
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "system" and "apiKeySource" in event:
            return str(event["apiKeySource"])
    return None


def auth_failed(lines: list[str]) -> str | None:
    """An authentication error in the stream (Claude Code's api_retry events, or the final result), else None."""
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        retry = event.get("type") == "system" and event.get("subtype") == "api_retry"
        if retry and (event.get("error_status") in (401, 403) or event.get("error") == "authentication_failed"):
            return f"authentication failed (HTTP {event.get('error_status')})"
        if event.get("type") == "result" and event.get("is_error"):
            text = str(event.get("result") or "")
            if "authenticate" in text.lower() or "api key is invalid" in text.lower():
                return text[:200]
    return None


def check_billing(billing: str, source: str | None) -> None:
    """`api` must be billed via ANTHROPIC_API_KEY; `plan` must never be. Unknown sources pass."""
    if billing == "api" and source is not None and source != "ANTHROPIC_API_KEY":
        raise BillingMismatch(f"--billing api, but Claude Code reports apiKeySource={source!r}. Stopping.")
    if billing == "plan" and source == "ANTHROPIC_API_KEY":
        raise BillingMismatch("--billing plan, but Claude Code is using ANTHROPIC_API_KEY. Stopping.")


class ClaudeAgent:
    def __init__(self, model: str, budget_per_prompt: float, billing: str = "plan") -> None:
        if billing not in BILLING:
            raise ValueError(f"billing must be one of {BILLING}")
        if billing == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
            raise BillingMismatch("--billing api needs ANTHROPIC_API_KEY set in this terminal.")
        self.model = model
        self.budget = budget_per_prompt
        self.billing = billing

    def run_session(self, work: Path, session: int, prompts: tuple[str, ...], use_plugin: bool,
                    log_dir: Path) -> SessionLog:  # fmt: skip
        log = SessionLog()
        dropped = {"VIRTUAL_ENV", "PYTHONPATH"} | ({"ANTHROPIC_API_KEY"} if self.billing == "plan" else set())
        env = {k: v for k, v in os.environ.items() if k not in dropped}
        env["PATH"] = os.pathsep.join([str(work / ".venv/bin"), str(work / "node_modules/.bin"), env.get("PATH", "")])
        session_id: str | None = None
        log_dir.mkdir(parents=True, exist_ok=True)
        for i, prompt in enumerate(prompts, start=1):
            cmd = ["claude", "-p", prompt, "--model", self.model, "--output-format", "stream-json", "--verbose",
                   "--max-budget-usd", str(self.budget), "--setting-sources", "project,local"]  # fmt: skip
            if session_id:
                cmd += ["--resume", session_id]
            if use_plugin:
                cmd += ["--plugin-dir", str(PLUGIN_DIR)]
            cmd += ["--allowedTools", *ALLOWED_TOOLS]
            result = PromptResult(session, i)
            try:
                out = subprocess.run(cmd, cwd=work, capture_output=True, text=True, env=env, timeout=PROMPT_TIMEOUT)
                stdout, stderr = out.stdout, out.stderr
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr, result.note = "", f"timed out after {PROMPT_TIMEOUT}s"
            (log_dir / f"s{session}p{i}.jsonl").write_text(stdout, encoding="utf-8")
            if stderr:
                (log_dir / f"s{session}p{i}.stderr.txt").write_text(stderr, encoding="utf-8")
            result.api_key_source = api_key_source(stdout.splitlines())
            check_billing(self.billing, result.api_key_source)
            failure = auth_failed(stdout.splitlines())
            if failure:
                raise AuthFailed(f"Claude Code could not authenticate: {failure}. Check the key, then rerun. Stopping.")
            final = parse_stream(stdout.splitlines())
            usage = final.get("usage") or {}
            result.cost_usd = float(final.get("total_cost_usd") or 0.0)
            result.turns = int(final.get("num_turns") or 0)
            result.duration_ms = int(final.get("duration_ms") or 0)
            result.input_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
            result.output_tokens = int(usage.get("output_tokens") or 0)
            result.is_error = bool(final.get("is_error")) or not final
            result.session_id = final.get("session_id") or session_id
            session_id = result.session_id
            log.results.append(result)
        return log


class FakeAgent:
    """For tests: applies a scripted edit per session instead of calling a model."""

    def __init__(self, edits: dict[int, Callable[[Path], None]]) -> None:
        self.edits = edits

    def run_session(self, work: Path, session: int, prompts: tuple[str, ...], use_plugin: bool,
                    log_dir: Path) -> SessionLog:  # fmt: skip
        if session in self.edits:
            self.edits[session](work)
        return SessionLog([PromptResult(session, i, cost_usd=0.01) for i in range(1, len(prompts) + 1)])
