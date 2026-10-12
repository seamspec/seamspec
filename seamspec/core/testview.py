"""What a rule test checks, read out of the test file (SPEC §15.1, ADR-20261011-8013).

A reading aid for the human reviewer: the test's check lines listed above the code, a few facts and
warnings. Model-free (§3) and built from the file alone, never from what the agent said about its
own test. It shows what is asserted, not whether that is enough.

- pytest: `assert` statements, `pytest.raises` / `pytest.warns` blocks, `pytest.fail(…)` calls,
  `raise AssertionError` and `self.assert…(…)` calls, found with Python's `ast`, so a commented-out
  assert or the word in a string doesn't count. A check made through a helper function isn't
  recognised, which is why "no checks found" is worded as a prompt to look, not as a verdict.
- vitest: lines containing `expect(`, found by a plain scan and labeled as such.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

LONG_TEST_LINES = 80
CHECK_TEXT_MAX = 110

# Modules a behavior test rarely needs: it should exercise the project's code, not the network or other programs.
PY_OUTSIDE = {"subprocess", "socket", "requests", "urllib", "http", "httpx", "aiohttp", "ftplib", "smtplib"}
JS_OUTSIDE = {"child_process", "http", "https", "net", "node-fetch", "axios", "undici"}
_JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\s+)['"](?:node:)?([\w@/.-]+)['"]""")


@dataclass
class Check:
    line: int  # 1-based line in the test file
    text: str  # the check, on one line


@dataclass
class TestView:
    lines: list[str]
    checks: list[Check] = field(default_factory=list)
    parsed: bool = True  # False: the checks come from a plain text scan, not from a parse
    warnings: list[str] = field(default_factory=list)

    @property
    def check_lines(self) -> set[int]:
        return {c.line for c in self.checks}

    def facts(self) -> str:
        n, c = len(self.lines), len(self.checks)
        return f"{n} line{'s' if n != 1 else ''} · {c} check{'s' if c != 1 else ''}"


def _one_line(text: str, limit: int = CHECK_TEXT_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _name(func: ast.expr) -> str:
    """The last name of what is called or raised: `pytest.fail` -> `fail`, `raises` -> `raises`."""
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def _raises_assertion(exc: ast.expr) -> bool:
    """`raise AssertionError` or `raise AssertionError("...")`."""
    return _name(exc.func if isinstance(exc, ast.Call) else exc) == "AssertionError"


def _is_raises(expr: ast.expr) -> bool:
    """`pytest.raises(...)`, `pytest.warns(...)`, or the bare names after `from pytest import raises`."""
    return isinstance(expr, ast.Call) and _name(expr.func) in ("raises", "warns", "deprecated_call")


def _python(code: str, view: TestView) -> None:
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        view.parsed = False
        view.warnings.append("the test file couldn't be parsed as Python, so the check list is a plain text scan")
        view.checks = [
            Check(i, _one_line(line)) for i, line in enumerate(view.lines, 1) if line.lstrip().startswith("assert ")
        ]
        return
    found: dict[int, str] = {}
    outside: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            found[node.lineno] = _one_line(ast.get_source_segment(code, node) or "assert …")
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                if _is_raises(item.context_expr):
                    found[node.lineno] = _one_line(
                        ast.get_source_segment(code, item.context_expr) or "pytest.raises(…)"
                    )
        elif (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert")
        ):
            found[node.lineno] = _one_line(ast.get_source_segment(code, node) or node.func.attr)  # unittest style
        elif isinstance(node, ast.Call) and _name(node.func) == "fail":  # pytest.fail(...), self.fail(...)
            found[node.lineno] = _one_line(ast.get_source_segment(code, node) or "fail(…)")
        elif isinstance(node, ast.Raise) and node.exc is not None and _raises_assertion(node.exc):
            found[node.lineno] = _one_line(ast.get_source_segment(code, node) or "raise AssertionError")
        elif isinstance(node, ast.Import):
            outside |= {alias.name.split(".")[0] for alias in node.names} & PY_OUTSIDE
        elif isinstance(node, ast.ImportFrom) and node.module:
            outside |= {node.module.split(".")[0]} & PY_OUTSIDE
    view.checks = [Check(line, text) for line, text in sorted(found.items())]
    _outside_warning(view, outside)


def _javascript(code: str, view: TestView) -> None:
    view.parsed = False
    view.checks = [Check(i, _one_line(line)) for i, line in enumerate(view.lines, 1) if "expect(" in line]
    _outside_warning(view, {m.group(1) for m in _JS_IMPORT.finditer(code)} & JS_OUTSIDE)


def _outside_warning(view: TestView, modules: set[str]) -> None:
    if modules:
        names = ", ".join(sorted(modules))
        view.warnings.append(f"it imports {names}: a behavior test rarely needs the network or other programs")


def analyze(code: str, runner: str) -> TestView:
    """Read a rule test. `runner` is the configured runner's name: `vitest` is scanned as
    JavaScript / TypeScript, anything else is parsed as Python."""
    view = TestView(lines=code.splitlines())
    (_javascript if runner == "vitest" else _python)(code, view)
    if not view.checks:
        view.warnings.insert(
            0,
            "no recognized assert / expect checks found: look for checks made another way (a helper, an "
            "exception); if there are none, this test passes whatever the code does",
        )
    if len(view.lines) > LONG_TEST_LINES:
        view.warnings.append(f"long test ({len(view.lines)} lines): a rule test should be short enough to read")
    return view
