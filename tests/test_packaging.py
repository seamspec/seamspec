"""What PyPI would receive (release rehearsal, 2026-10-24): the built wheel and sdist carry the licence and
every file of the package, and nothing from outside it (notes, benchmark results, the plugin). Since 0.1.0
(ADR-20261027-5e17): one version everywhere, and a README whose links work on pypi.org."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

from seamspec import __version__
from seamspec.installers import ci

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[set[str], set[str]]:
    if shutil.which("uv") is None:
        pytest.skip("uv not installed")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["uv", "build", "-q", "--out-dir", str(out)], cwd=ROOT, check=True, capture_output=True)
    wheel = set(zipfile.ZipFile(next(out.glob("*.whl"))).namelist())
    with tarfile.open(next(out.glob("*.tar.gz"))) as sdist:
        source = {name.split("/", 1)[1] for name in sdist.getnames() if "/" in name}
    return wheel, source


def test_both_carry_the_licence(built: tuple[set[str], set[str]]) -> None:
    wheel, source = built
    assert any(name.endswith(".dist-info/licenses/LICENSE") for name in wheel)
    assert "LICENSE" in source


def test_the_wheel_has_every_package_file(built: tuple[set[str], set[str]]) -> None:
    tracked = subprocess.run(["git", "ls-files", "seamspec"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert tracked and not set(tracked) - built[0]  # templates, schemas, known directive lines


def test_the_sdist_has_nothing_from_outside_the_package(built: tuple[set[str], set[str]]) -> None:
    top = {name.split("/")[0] for name in built[1]}
    assert top <= {"seamspec", "README.md", "LICENSE", "pyproject.toml", "PKG-INFO"}, top


def test_one_version_everywhere() -> None:
    """The package, the CLI and the plugin say the same version. A release also has a changelog entry."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    plugin = json.loads((ROOT / "seamspec-plugin/.claude-plugin/plugin.json").read_text("utf-8"))["version"]
    assert pyproject == __version__
    if ci.released():
        assert plugin == __version__
        assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text("utf-8")


def test_readme_links_work_on_pypi() -> None:
    """PyPI shows the README without the repository around it, so a relative link leads nowhere."""
    targets = re.findall(r"\]\(([^)\s]+)\)", (ROOT / "README.md").read_text("utf-8"))
    assert targets and [t for t in targets if not t.startswith(("https://", "#"))] == []
