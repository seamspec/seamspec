"""The CI workflow and CODEOWNERS that `seamspec init` installs (SPEC §7.3, §16.5).

`.github/workflows/seamspec.yml` runs `seamspec doctor --ci` and `seamspec verify --all --ci` on
every pull request. The toolchain steps come from the configured runners and the lockfiles found in
the repo. An existing workflow file is never overwritten. In strict mode, a marked CODEOWNERS block
asks a lead to review every change to the ledger and to the rule tests.
"""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from .. import __version__
from ..core.config import Config
from ..core.store import atomic_write

WORKFLOW_REL = ".github/workflows/seamspec.yml"
CODEOWNERS_REL = ".github/CODEOWNERS"
OWNERS_BEGIN = "# seamspec:begin (managed by `seamspec init`; replace @your-team/leads)"
OWNERS_END = "# seamspec:end"
REPOSITORY = "https://github.com/seamspec/seamspec"
_RELEASE = re.compile(r"\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?")  # PEP 440 versions that get published


def released(version: str | None = None) -> bool:
    """Is this SeamSpec a published version? A development build (`0.1.0.dev0`, a local `+tag`) is not:
    a CI runner can't install it by version (dogfooding finding #1, ADR-20261011-a9f3)."""
    return _RELEASE.fullmatch(__version__ if version is None else version) is not None


def install_step(version: str | None = None) -> list[str]:
    """How the workflow gets SeamSpec. A release: the version that wrote the file, so CI and the
    developer's machine run the same SeamSpec. A development build: from the repository."""
    version = __version__ if version is None else version
    if released(version):
        return [
            "      # The SeamSpec version that wrote this file. When you upgrade SeamSpec, update this line too.",
            f'      - run: uv tool install "seamspec=={version}"',
        ]
    return [
        "      # This file was written by an unreleased SeamSpec, so it installs SeamSpec from its repository,",
        "      # which your CI must be able to read. After the release, replace it with a version:",
        '      #   - run: uv tool install "seamspec==<version>"',
        f'      - run: uv tool install "git+{REPOSITORY}@main"',
    ]


def _toolchain(root: Path, cfg: Config) -> list[str]:
    """Steps that install what the rule tests need, from the runners and the lockfiles present."""
    steps: list[str] = []
    if "pytest" in cfg.runners:
        if (root / "uv.lock").is_file():
            steps += ["      - run: uv sync --locked  # the project's .venv; SeamSpec finds pytest there"]
        elif (root / "requirements.txt").is_file():
            steps += ["      - run: uv venv && uv pip install -r requirements.txt pytest"]
        else:
            steps += ["      - run: uv venv && uv pip install pytest  # add your project's dependencies here"]
    if "vitest" in cfg.runners:
        steps += ["      - uses: actions/setup-node@v4", "        with:", "          node-version: 22"]
        steps += ["      - run: npm ci" if (root / "package-lock.json").is_file() else "      - run: npm install"]
    if not steps:
        steps = ["      # Install your project's toolchain and dependencies here, so the rule tests can run."]
    return steps


def render_workflow(root: Path, cfg: Config) -> str:
    template = files("seamspec.templates").joinpath("seamspec.yml").read_text("utf-8")
    template = template.replace("{{install}}", "\n".join(install_step()))
    return template.replace("{{toolchain}}", "\n".join(_toolchain(root, cfg)))


def install_workflow(root: Path, cfg: Config) -> str:
    """created | kept (an existing file is never overwritten)."""
    path = root / WORKFLOW_REL
    if path.exists():
        return "kept"
    atomic_write(path, render_workflow(root, cfg))
    return "created"


def owner_lines(cfg: Config) -> list[str]:
    """`/.seamspec/` plus each runner's harness folder (§12A.5)."""
    dirs = ["/.seamspec/", *(f"/{r.harness_dir.strip('/')}/" for r in cfg.runners.values())]
    unique = list(dict.fromkeys(dirs))
    return [f"{d} @your-team/leads" for d in unique]


def install_codeowners(root: Path, cfg: Config) -> str:
    """created | updated | unchanged. Only the marked block is SeamSpec's; the rest is never touched."""
    path = root / CODEOWNERS_REL
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = "\n".join([OWNERS_BEGIN, *owner_lines(cfg), OWNERS_END]) + "\n"
    pattern = re.compile(re.escape(OWNERS_BEGIN) + r".*?" + re.escape(OWNERS_END) + r"\n?", re.S)
    if pattern.search(old):
        new = pattern.sub(lambda _: block, old, count=1)
    else:
        new = old + ("\n" if old and not old.endswith("\n") else "") + block
    if new == old:
        return "unchanged"
    atomic_write(path, new)
    return "updated" if old else "created"
