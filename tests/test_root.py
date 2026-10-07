from __future__ import annotations

from pathlib import Path

import pytest

from seamspec.core.root import RootNotFound, find_root, to_rel


def test_find_root_walks_up(repo: Path) -> None:
    deep = repo / "src" / "a" / "b"
    deep.mkdir(parents=True)
    assert find_root(deep) == repo.resolve()


def test_find_root_not_found(tmp_path: Path) -> None:
    with pytest.raises(RootNotFound, match="seamspec init") as err:
        find_root(tmp_path)
    assert f"in {tmp_path.resolve()} or any folder above it" in str(err.value)  # says where it looked


def test_find_root_env_wins(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    monkeypatch.setenv("SEAMSPEC_ROOT", str(repo))
    assert find_root(elsewhere) == repo.resolve()


def test_find_root_env_must_be_initialised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ROOT", str(tmp_path))
    with pytest.raises(RootNotFound, match="SEAMSPEC_ROOT"):
        find_root()


def test_to_rel(tmp_path: Path) -> None:
    assert to_rel(tmp_path, tmp_path / "src" / "x.py") == "src/x.py"
    assert to_rel(tmp_path, "src/x.py") == "src/x.py"
    assert to_rel(tmp_path, tmp_path / "src" / ".." / "y.py") == "y.py"
    assert to_rel(tmp_path, tmp_path.parent / "outside.py") is None
    assert to_rel(tmp_path, "../outside.py") is None


def test_to_rel_resolves_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert to_rel(link, real / "a.py") == "a.py"
