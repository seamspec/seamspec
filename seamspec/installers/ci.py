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


PLACEHOLDER_OWNER = "@your-team/leads"


def owner_lines(cfg: Config, owners: dict[str, str] | None = None) -> list[str]:
    """`/.seamspec/` plus each runner's harness folder (§12A.5). `owners`: the reviewers already
    written in the block, by folder; a new folder gets the ones on the block's first line."""
    dirs = ["/.seamspec/", *(f"/{r.harness_dir.strip('/')}/" for r in cfg.runners.values())]
    owners = owners or {}
    fallback = next(iter(owners.values()), PLACEHOLDER_OWNER)
    return [f"{d} {owners.get(d, fallback)}" for d in dict.fromkeys(dirs)]


# Any `# seamspec:begin` line opens the block: a find-and-replace of the placeholder changes its words too.
_BLOCK = re.compile(r"^# seamspec:begin\b[^\n]*\n.*?" + re.escape(OWNERS_END) + r"\n?", re.S | re.M)


def owners_block(text: str) -> str | None:
    """SeamSpec's block in a CODEOWNERS file, or None."""
    found = _BLOCK.search(text)
    return found.group(0) if found else None


def _entries(block: str) -> list[tuple[str, list[str]]]:
    """(folder, owners) for each entry line. Any whitespace separates them (tabs too); a `#` word starts
    a comment, on its own line or after the owners, and is never read as an owner (Copilot on #103)."""
    out = []
    for line in block.splitlines():
        words = line.split()
        if "#" in (cut := [w[:1] for w in words]):
            words = words[: cut.index("#")]
        if words:
            out.append((words[0], words[1:]))
    return out


def placeholder_left(text: str) -> bool:
    """Does an entry in SeamSpec's block still name `@your-team/leads`? Comments don't count (#103)."""
    block = owners_block(text)
    return block is not None and any(PLACEHOLDER_OWNER in owners for _, owners in _entries(block))


def _owners_in(block: str) -> dict[str, str]:
    """The reviewers a person put in SeamSpec's block, by folder (placeholders left out)."""
    found = {}
    for folder, owners in _entries(block):
        if real := [o for o in owners if o != PLACEHOLDER_OWNER]:  # a real reviewer next to it stays
            found[folder] = " ".join(real)
    return found


def install_codeowners(root: Path, cfg: Config) -> str:
    """created | updated | unchanged. Only the marked block is SeamSpec's; the rest is never touched.
    Reviewers written in the block are kept: rerunning `init` must not put the placeholder back."""
    path = root / CODEOWNERS_REL
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    found = owners_block(old)
    lines = owner_lines(cfg, _owners_in(found) if found else None)
    block = "\n".join([OWNERS_BEGIN, *lines, OWNERS_END]) + "\n"
    if found:
        new = _BLOCK.sub(lambda _: block, old, count=1)
    else:
        new = old + ("\n" if old and not old.endswith("\n") else "") + block
    if new == old:
        return "unchanged"
    atomic_write(path, new)
    return "updated" if old else "created"
