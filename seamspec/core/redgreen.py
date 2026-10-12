"""Red-green check: does a proposed test fail *without* the change? (SPEC §11.4)

Information for the human reviewer, never a gate. A test that already passes on `HEAD` either
protects behavior that existed before (fine for characterization tests) or checks nothing (a
strong hint on a brand-new feature).

How: run the proposed test on the working tree, then in a temporary detached `git worktree` of
`HEAD`. The worktree gets SeamSpec's *current* settings (config.toml and each runner's config
files, so both runs use the same runner) and links to the project's `.venv` / `node_modules`,
which a fresh worktree doesn't have. The worktree is always removed afterwards.

The HEAD run must import HEAD's code. A project installed in editable mode (`uv sync`,
`pip install -e`) has its virtualenv point at the *working tree*, so the linked `.venv` would hand
the HEAD run today's code and the answer would be a false "no" (dogfooding finding,
ADR-20261011-3c7e). So the HEAD run starts the runner through a copy of its start script that first
points every import path inside the repository at the worktree. Only PATH is used for that, never a
new environment variable (§12.4.7). Where that can't be done and an editable install is present,
the answer is "n/a", never a guess.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import verifier
from .config import Config
from .lifecycle import LifecycleError, harness_in_place
from .models import Invariant
from .root import CONFIG_REL
from .store import Store

Verdict = Literal["yes", "no", "n/a"]
LINKED = (".venv", "venv", "node_modules")


# What a HEAD failure looks like when the code under test simply isn't there yet (dogfooding #9,
# ADR-20261013-a5d3): the test can't import or find what it tests. Matched against the first line
# of each failure in the runner's report, never against terminal output.
MISSING_CODE = re.compile(
    r"^(ModuleNotFoundError|ImportError|FileNotFoundError|NameError)\b"
    r"|^AttributeError: (partially initialized )?(module|type object) .*\bhas no attribute\b"
    r"|Cannot find module|Failed to resolve import|does not provide an export named"
    r"|\bis not a function\b|\bis not defined\b|\bis not a constructor\b"
)
ON_HEAD_MAX = 120


@dataclass
class RedGreen:
    verdict: Verdict  # "yes" = fails without the change (good), "no" = passes on HEAD too
    detail: str  # one line for the reviewer
    # "yes", but only because HEAD doesn't have the code the test needs. True for any test of new
    # code, so it says nothing about whether the test would catch a wrong change.
    new_code: bool = False
    proposal_id: str | None = None

    def line(self) -> str:
        """The one line the reviewer reads: the verdict in capitals, then why."""
        verdict = {"yes": "YES", "no": "NO", "n/a": "COULDN'T TELL"}[self.verdict]
        if self.new_code:
            verdict = "YES, BUT ONLY BECAUSE THE CODE IS NEW"
        return f"Fails without your change: {verdict} ({self.detail})"

    def hint(self) -> str | None:
        """What the reviewer can do when the verdict proves little."""
        if not self.new_code:
            return None
        target = f" --proposed {self.proposal_id}" if self.proposal_id else ""
        return (
            "To see this test catch something: break the new code on purpose, run "
            f"`seamspec verify{target}`, and check that it fails."
        )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ran_tests(report: verifier.VerifyReport) -> bool:
    """False when the run couldn't really happen (deadline, missing runner, config mismatch)."""
    if report.config_failures or report.integrity_failures or report.incomplete:
        return False
    return not any(r.could_not_run for r in report.results)


def check(store: Store, cfg: Config, inv: Invariant) -> RedGreen:
    root = store.root
    prints = verifier.current_fingerprints(root, cfg)

    # 1. Working tree: the proposal should pass here.
    try:
        with harness_in_place(store, cfg, inv) as staged:
            now = verifier.run(root, cfg, [staged], fingerprints=prints)
    except (LifecycleError, OSError) as exc:
        return RedGreen("n/a", f"couldn't run it here: {exc}")
    if not _ran_tests(now):
        return RedGreen("n/a", "the test couldn't run on your working tree")
    if not now.passed:
        return RedGreen("n/a", "it fails on your working tree too, so approval would be refused")

    # 2. HEAD, in a throwaway worktree.
    prefix = _git(root, "rev-parse", "--show-prefix")
    head = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    if prefix is None or prefix.returncode != 0:
        return RedGreen("n/a", "not a git repository, so there's no HEAD to compare with")
    if head is None or head.returncode != 0:
        return RedGreen("n/a", "no commits yet, so there's no HEAD to compare with")

    tmp = Path(tempfile.mkdtemp(prefix="seamspec-redgreen-"))
    wt = tmp / "head"
    added = _git(root, "worktree", "add", "--detach", "-q", str(wt), "HEAD")
    try:
        if added is None or added.returncode != 0:
            return RedGreen("n/a", "couldn't create a temporary worktree of HEAD")
        wt_root = wt / prefix.stdout.strip()
        try:
            wt_root.mkdir(parents=True, exist_ok=True)
            _prepare(root, wt_root, cfg, inv)
        except OSError as exc:  # e.g. symlinks not allowed (Windows), permissions
            return RedGreen("n/a", f"couldn't prepare the HEAD copy: {exc}")
        runner = cfg.runners[inv.verification.runner]
        staged_head = inv.model_copy(
            update={"verification": inv.verification.model_copy(update={"harness_path": runner.harness_path(inv.id)})}
        )
        top = _git(root, "rev-parse", "--show-toplevel")
        top_dir = Path(top.stdout.strip()) if top is not None and top.returncode == 0 else root
        shims = tmp / "bin"
        try:
            redirected = _shim_runner(cfg, inv.verification.runner, wt_root, shims, top_dir, wt)
            before = verifier.run(
                wt_root, cfg, [staged_head], fingerprints=prints, first_on_path=[str(shims)] if redirected else ()
            )
        except OSError as exc:
            return RedGreen("n/a", f"couldn't run the test against HEAD: {exc}")
        applied = (shims / APPLIED).exists()
        if redirected and not applied:
            # The copied start script didn't get through its first lines, so a failure here says
            # nothing about the test. Never read that as "fails without your change".
            return RedGreen("n/a", "the test runner couldn't be started for the last commit's code")
        if editable_install(root, top_dir, os.environ) and not applied:
            return RedGreen("n/a", "this project is installed in editable mode, and the test couldn't be pointed at "
                            "the last commit's code")  # fmt: skip
    finally:
        _git(root, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(tmp, ignore_errors=True)
        _git(root, "worktree", "prune")

    if not _ran_tests(before):
        return RedGreen("n/a", "the test couldn't run against HEAD")
    if before.passed:
        return RedGreen("no", "it passes on HEAD too: fine if it protects behavior that already existed")
    said = _head_failures(before, inv.id)
    if said and all(MISSING_CODE.search(message) for message in said):
        return RedGreen(
            "yes",
            f"the last commit doesn't have what this test needs: {_cut(said[0])}. Expected for new code, but it "
            "doesn't show the test would catch a wrong change",
            new_code=True,
            proposal_id=inv.id,
        )
    on_head = f"; on HEAD: {_cut(said[0])}" if said else ""
    return RedGreen("yes", f"it fails on HEAD and passes with your change{on_head}")


def _head_failures(report: verifier.VerifyReport, inv_id: str) -> list[str]:
    """The first line of each failure of this test on HEAD, when the runner's report gives them."""
    return [check.message for result in report.results for check in result.checks.get(inv_id, [])]


def _cut(text: str) -> str:
    return text if len(text) <= ON_HEAD_MAX else text[: ON_HEAD_MAX - 1].rstrip() + "…"


def _prepare(root: Path, wt_root: Path, cfg: Config, inv: Invariant) -> None:
    """Give the HEAD worktree today's SeamSpec settings, the proposed test and the project's envs."""
    files = [CONFIG_REL.as_posix(), *(rel for r in cfg.runners.values() for rel in r.config_files)]
    for rel in files:
        src = root / rel
        if src.is_file():
            dst = wt_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    runner = cfg.runners[inv.verification.runner]
    dst = wt_root / runner.harness_path(inv.id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / inv.verification.harness_path, dst)
    for name in LINKED:
        src = root / name
        if src.exists() and not (wt_root / name).exists():
            (wt_root / name).symlink_to(src.resolve(), target_is_directory=True)


# --- the HEAD run imports HEAD's code ---------------------------------------------------------------

APPLIED = "applied"  # written by the redirect when it has run

# Runs first in the runner's start script. It moves every import path inside the repository to the
# same place in the HEAD worktree: sys.path entries (a `.pth` editable install, PYTHONPATH) and the
# tables of import-hook editable installs (`__editable__*` modules). The interpreter's own folders
# are left alone, since a virtualenv usually sits inside the repository.
_REDIRECT = """\
def _redirect():
    import os, sys
    src, dst, here = {src!r}, {dst!r}, {here!r}
    own = [os.path.normcase(os.path.realpath(p)) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix)]
    inside = os.path.normcase(src)
    def move(path):
        if not isinstance(path, str) or not path:
            return path
        real = os.path.realpath(path)
        key = os.path.normcase(real)
        if any(key == o or key.startswith(o + os.sep) for o in own):
            return path
        if key == inside or key.startswith(inside + os.sep):
            return dst + real[len(src):]
        return path
    sys.path[:] = [move(p) for p in sys.path]
    for name, module in list(sys.modules.items()):
        if name.startswith("__editable__"):
            for attr in ("MAPPING", "NAMESPACES"):
                table = getattr(module, attr, None)
                if isinstance(table, dict):
                    for k, v in list(table.items()):
                        table[k] = [move(x) for x in v] if isinstance(v, list) else move(v)
    sys.path_importer_cache.clear()
    try:
        open(os.path.join(here, {applied!r}), "w").close()
    except OSError:
        pass
_redirect()
del _redirect
"""


def _shim_runner(cfg: Config, name: str, wt_root: Path, shims: Path, top: Path, wt: Path) -> bool:
    """Write a copy of runner `name`'s start script that redirects imports first. False when the
    runner isn't started from a Python script SeamSpec can copy (a path, a binary, a Windows launcher)."""
    runner = cfg.runners[name]
    command = runner.cmd[0]
    if "/" in command or os.sep in command:
        return False
    # The same environment the verifier starts this runner with, so a runner's own PATH counts.
    env = verifier.runner_env(wt_root, cfg, runner, wt_root / verifier.REPORTS_REL / f"{name}.xml")
    found = shutil.which(command, path=env.get("PATH", ""))
    return found is not None and write_shim(Path(found), shims, top, wt)


def write_shim(script: Path, shims: Path, top: Path, wt: Path) -> bool:
    """Copy `script` into `shims` with the redirect inserted. False if it isn't a Python start script,
    or if the copy wouldn't compile: a copy that can't start would look like a failing test."""
    try:
        lines = script.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return False
    at = _insert_at(lines)
    if at is None:
        return False
    redirect = _REDIRECT.format(
        src=os.path.realpath(top), dst=os.path.realpath(wt), here=str(shims.resolve()), applied=APPLIED
    )
    text = "".join(lines[:at]) + redirect + "".join(lines[at:])
    if "python" in lines[0].lower():  # a pure Python script: check the copy before trusting it
        try:
            compile(text, str(script), "exec")
        except (SyntaxError, ValueError):
            return False
    shims.mkdir(parents=True, exist_ok=True)
    target = shims / script.name
    target.write_text(text, encoding="utf-8")
    target.chmod(0o755)
    return True


def _insert_at(lines: list[str]) -> int | None:
    """Where the redirect goes in a Python start script: after the `#!` line, or after the three-line
    `#!/bin/sh` + `'''exec'` header that installers write when the interpreter path is long."""
    if not lines or not lines[0].startswith("#!"):
        return None
    if any(line.lstrip().startswith("from __future__") for line in lines):
        return None  # must stay the first statement, wherever the comments and docstring end
    if "python" in lines[0].lower():
        return 1
    if len(lines) >= 3 and lines[1].startswith("'''exec'") and "python" in lines[1].lower():
        return 3
    return None


def _site_packages(roots: list[Path], environ: Mapping[str, str]) -> Iterator[Path]:
    venvs = [r / name for r in roots for name in (".venv", "venv")]
    if environ.get("VIRTUAL_ENV"):
        venvs.append(Path(environ["VIRTUAL_ENV"]))
    for venv in dict.fromkeys(venvs):
        yield from venv.glob("lib/python*/site-packages")
        yield from venv.glob("Lib/site-packages")


def _inside(path: str, top: Path, site: Path) -> bool:
    """An absolute path inside the repository, but not inside the virtualenv itself."""
    candidate = Path(path)
    if not candidate.is_absolute():
        return False
    real, top_real = os.path.realpath(candidate), os.path.realpath(top)
    venv = os.path.realpath(site.parents[2] if site.parent.name.startswith("python") else site.parents[1])
    under = real == top_real or real.startswith(top_real + os.sep)
    return under and not (real == venv or real.startswith(venv + os.sep))


def editable_install(root: Path, top: Path, environ: Mapping[str, str]) -> bool:
    """Does a virtualenv this project uses import code from inside the repository? True for an
    editable install: a `.pth` line, an `__editable__` import hook, or `direct_url.json` saying so."""
    for site in _site_packages(list(dict.fromkeys([root, top])), environ):
        for pth in site.glob("*.pth"):
            try:
                lines = pth.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in (ln.strip() for ln in lines):
                if line and not line.startswith(("#", "import ", "import\t")) and _inside(line, top, site):
                    return True
        for hook in site.glob("__editable__*.py"):
            try:
                if os.path.realpath(top) in hook.read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                continue
        for record in site.glob("*.dist-info/direct_url.json"):
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            url = data.get("url", "") if isinstance(data, dict) else ""
            editable = (
                isinstance(data, dict) and isinstance(data.get("dir_info"), dict) and data["dir_info"].get("editable")
            )
            if editable and url.startswith("file://") and _inside(url[len("file://") :], top, site):
                return True
    return False
