from __future__ import annotations

import json
from importlib.resources import files

import pytest

from seamspec.core.config import Config, ConfigError, RunnerCfg, config_json_schema, parse_config
from seamspec.core.runners import V01_PRESETS, preset
from seamspec.core.schemas import validation_errors
from seamspec.installers.scaffold import render_config


def test_presets_load() -> None:
    for name in V01_PRESETS:
        cfg = preset(name)
        assert "{each}" in cfg.cmd and "{report}" in " ".join(cfg.cmd)
        assert cfg.report == "junit"


def test_harness_paths_and_protect_globs() -> None:
    pytest_cfg, vitest_cfg = preset("pytest"), preset("vitest")
    assert pytest_cfg.harness_path("inv_1a2b3c4d") == ".seamspec/tests/test_inv_1a2b3c4d.py"
    assert pytest_cfg.protect_glob() == ".seamspec/tests/test_inv_*.py"
    assert vitest_cfg.protect_glob() == "tests/seamspec/inv_*.test.ts"
    go_like = RunnerCfg(cmd=["go", "test"], harness_dir="internal/seamspec", filename="{id}/seamspec_test.go")
    assert go_like.protect_glob() == "internal/seamspec/inv_*/**"


@pytest.mark.parametrize(
    "field,value",
    [
        ("harness_dir", "../outside"),
        ("harness_dir", "/abs/path"),
        ("filename", "test_no_id.py"),
        ("config_files", ["../x.ini"]),
    ],
)
def test_runner_rejects_bad_paths(field: str, value) -> None:
    data = {"cmd": ["pytest"], "filename": "test_{id}.py", field: value}
    with pytest.raises(ValueError):
        RunnerCfg.model_validate(data)


@pytest.mark.parametrize("mode", ["advisory", "enforced", "strict"])
@pytest.mark.parametrize("runners", [[], ["pytest"], ["pytest", "vitest"]])
def test_generated_config_loads(mode: str, runners: list[str]) -> None:
    cfg = parse_config(render_config(mode, runners))
    assert cfg.mode == mode
    assert sorted(cfg.runners) == sorted(runners)


def test_no_runners_writes_commented_presets() -> None:
    text = render_config("enforced", [])
    assert "# [runners.pytest]" in text and "# [runners.vitest]" in text


def test_strict_defaults_apply_when_unset() -> None:
    cfg = parse_config('mode = "strict"\n')
    assert cfg.hooks.fail_closed is True
    assert cfg.execution.trust_level == "harness"
    assert cfg.review.chat_approvals is False  # ADR-20261006-c300
    assert parse_config('mode = "enforced"\n').review.chat_approvals is True


def test_explicit_value_beats_strict_default() -> None:
    cfg = parse_config('mode = "strict"\n[hooks]\nfail_closed = false\n[review]\nchat_approvals = true\n')
    assert cfg.hooks.fail_closed is False
    assert cfg.execution.trust_level == "harness"
    assert cfg.review.chat_approvals is True


def test_strict_written_by_init_is_explicit() -> None:
    cfg = parse_config(render_config("strict", ["pytest"]))
    assert cfg.hooks.fail_closed is True and cfg.execution.trust_level == "harness"
    assert cfg.review.chat_approvals is False
    assert parse_config(render_config("enforced", ["pytest"])).review.chat_approvals is True


def test_unknown_key_is_an_error() -> None:
    with pytest.raises(ConfigError, match="timout_seconds"):
        parse_config("[verify]\ntimout_seconds = 5\n")


def test_invalid_toml_is_an_error() -> None:
    with pytest.raises(ConfigError, match="invalid TOML"):
        parse_config("mode = \n")


def test_packaged_config_schema_matches_model() -> None:
    packaged = json.loads(files("seamspec.schemas").joinpath("v1", "config.json").read_text("utf-8"))
    assert packaged == config_json_schema(), (
        "schemas/v1/config.json is stale; regenerate it from seamspec.core.config.config_json_schema()"
    )


def test_generated_config_validates_against_json_schema() -> None:
    import tomllib

    data = tomllib.loads(render_config("enforced", ["pytest", "vitest"]))
    assert validation_errors("config", data) == []
    assert validation_errors("config", {"bogus": 1})
    assert Config.model_validate(data).runners["pytest"].report == "junit"


def test_stop_deadline_must_stay_below_the_hook_timeout() -> None:
    """Copilot on #18: a deadline at or above the 300 s hook timeout would let Claude Code kill the hook
    and discard its decision, a silent fail-open."""
    from seamspec.core.config import HOOK_TIMEOUT_SECONDS, MAX_STOP_DEADLINE

    assert MAX_STOP_DEADLINE < HOOK_TIMEOUT_SECONDS
    assert parse_config(f"[verify]\nstop_deadline_seconds = {MAX_STOP_DEADLINE}\n").verify.stop_deadline_seconds == 270
    with pytest.raises(ConfigError, match="stop_deadline_seconds"):
        parse_config("[verify]\nstop_deadline_seconds = 300\n")


def test_plugin_stop_timeout_matches_the_config_cap() -> None:
    import json
    from pathlib import Path

    from seamspec.core.config import HOOK_TIMEOUT_SECONDS

    hooks = json.loads((Path(__file__).resolve().parents[1] / "seamspec-plugin/hooks/hooks.json").read_text())
    assert hooks["hooks"]["Stop"][0]["hooks"][0]["timeout"] == HOOK_TIMEOUT_SECONDS
