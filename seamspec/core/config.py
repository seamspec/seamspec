"""`.seamspec/config.toml` model and loader (SPEC §9.5, §12A.3, §19.2)."""

from __future__ import annotations

import tomllib
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .root import CONFIG_REL


class _Strict(BaseModel):
    # A typo in config.toml must be an error, not a silently ignored key.
    model_config = ConfigDict(extra="forbid")


def _inside_repo(v: str) -> str:
    p = PurePosixPath(v)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"{v!r} must be a relative path inside the repo")
    return v


class RunnerCfg(_Strict):
    cmd: list[str] = Field(min_length=1)  # argv tokens; {each} and {report} are expanded
    filename: str  # e.g. "test_{id}.py" or "{id}/seamspec_test.go"
    harness_dir: str = ".seamspec/tests"
    each: list[str] = Field(default_factory=lambda: ["{path}"])  # vars: {path} {dir} {stem} {id}
    report: Literal["junit", "go-test-json", "none"] = "none"
    env: dict[str, str] = Field(default_factory=dict)  # runner-only env; may use {report}
    paths: list[str] = Field(default_factory=list)  # project files this runner covers
    config_files: list[str] = Field(default_factory=list)  # fingerprinted + protected (§12.2)

    @field_validator("harness_dir", "filename")
    @classmethod
    def _path_inside_repo(cls, v: str) -> str:
        return _inside_repo(v)

    @field_validator("filename")
    @classmethod
    def _filename_has_id(cls, v: str) -> str:
        if "{id}" not in v:
            raise ValueError("filename must contain {id}; failure attribution relies on it (§12A.4)")
        return v

    @field_validator("config_files")
    @classmethod
    def _config_inside_repo(cls, v: list[str]) -> list[str]:
        return [_inside_repo(x) for x in v]

    def harness_path(self, inv_id: str) -> str:
        return str(PurePosixPath(self.harness_dir) / self.filename.format(id=inv_id))

    def protect_glob(self) -> str:
        """Glob covering every harness of this runner (§12A.5)."""
        rel = PurePosixPath(self.harness_dir) / self.filename.format(id="inv_*")
        return f"{rel.parent}/**" if "inv_*" in rel.parent.name else str(rel)


HOOK_TIMEOUT_SECONDS = 300  # seamspec-plugin/hooks/hooks.json, Stop
MAX_STOP_DEADLINE = HOOK_TIMEOUT_SECONDS - 30  # leave time to start up, attribute and print


class VerifyCfg(_Strict):
    timeout_seconds: int = Field(default=120, ge=1)
    # One overall budget per hook/gate run (§12.2). Capped below the plugin's 300 s Stop hook timeout:
    # a hook Claude Code kills has its decision discarded, which would silently let the agent stop.
    stop_deadline_seconds: int = Field(default=240, ge=10, le=MAX_STOP_DEADLINE)
    max_output_chars: int = Field(default=4000, ge=200)
    max_stop_retries: int = Field(default=3, ge=0)
    run_on_stop: Literal["auto", "all", "scoped"] = "auto"
    stop_all_threshold: int = Field(default=100, ge=1)  # auto: all below, scoped at/above
    isolate_on_failure: int = Field(default=10, ge=0)  # max one-at-a-time reruns for attribution


class HooksCfg(_Strict):
    gate_mode: Literal["context", "deny_once", "off"] = "context"
    fail_closed: bool = False


class BraindumpCfg(_Strict):
    path: str = "BRAINDUMP.md"
    marker: str = "<!-- seamspec:processed -->"
    redact_secrets: bool = True
    nudge: Literal["ask", "off"] = "ask"


class ProtectCfg(_Strict):
    paths: list[str] = Field(default_factory=lambda: [".seamspec/**"])


class CommandsCfg(_Strict):
    namespace: str = "seamspec"
    hosts: list[str] = Field(default_factory=lambda: ["auto"])
    max_proposals_per_run: int = Field(default=3, ge=1)


class ProposalsCfg(_Strict):
    max_pending: int = Field(default=10, ge=1)  # project-wide PROPOSED backlog cap


class ReviewCfg(_Strict):
    # Approve, reject and supersede in a chat dialog (ADR-20261006-c300). Off by default in every mode
    # until Claude Code shows the whole dialog: the CLI folds it to a few lines, the desktop app
    # declines it unseen (verification 2, ADR-20261008-5d1e).
    chat_approvals: bool = False


class ExecutionCfg(_Strict):
    run_proposed: Literal["auto", "host", "ask", "never"] = "auto"
    env_passthrough: list[str] = Field(default_factory=list)
    trust_level: Literal["runners", "harness"] = "runners"


class Config(_Strict):
    schema_version: Literal["1"] = "1"
    mode: Literal["advisory", "enforced", "strict"] = "enforced"
    verify: VerifyCfg = Field(default_factory=VerifyCfg)
    # Empty when `init` detected no language: presets are then written commented out (§12A.7).
    runners: dict[str, RunnerCfg] = Field(default_factory=dict)
    hooks: HooksCfg = Field(default_factory=HooksCfg)
    braindump: BraindumpCfg = Field(default_factory=BraindumpCfg)
    protect: ProtectCfg = Field(default_factory=ProtectCfg)
    commands: CommandsCfg = Field(default_factory=CommandsCfg)
    proposals: ProposalsCfg = Field(default_factory=ProposalsCfg)
    execution: ExecutionCfg = Field(default_factory=ExecutionCfg)
    review: ReviewCfg = Field(default_factory=ReviewCfg)

    @model_validator(mode="after")
    def _strict_defaults(self) -> Config:
        """strict mode tightens defaults the user did not set explicitly in config.toml."""
        if self.mode == "strict":
            if "fail_closed" not in self.hooks.model_fields_set:
                self.hooks.fail_closed = True
            if "trust_level" not in self.execution.model_fields_set:
                self.execution.trust_level = "harness"
        return self


class ConfigError(RuntimeError):
    pass


def parse_config(text: str, source: str = str(CONFIG_REL)) -> Config:
    try:
        return Config.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: invalid TOML: {exc}") from exc
    except ValidationError as exc:
        raise ConfigError(f"{source}: {exc}") from exc


def load_config(root: Path) -> Config:
    path = root / CONFIG_REL
    return parse_config(path.read_text(encoding="utf-8"), str(path))


CONFIG_SCHEMA_ID = "https://seamspec.github.io/schemas/v1/config.json"


def config_json_schema() -> dict:
    """JSON Schema for config.toml, generated from the model so the two can't drift.
    The packaged `schemas/v1/config.json` must equal this (checked by the tests)."""
    schema = Config.model_json_schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": CONFIG_SCHEMA_ID, **schema}
