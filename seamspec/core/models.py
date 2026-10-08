"""Ledger record models (SPEC §10, §19.3).

These mirror the JSON Schemas in `seamspec/schemas/v1/`; the tests check that every record
these models write validates against the packaged schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

INV_ID = r"^inv_[a-f0-9]{8}$"
DE_ID = r"^de_[a-f0-9]{8}$"
ADR_ID = r"^ADR-[0-9]{8}-[a-f0-9]{4}$"
SHA256 = r"^[a-f0-9]{64}$"


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")  # schemas use additionalProperties: false


Via = Literal["terminal", "chat"]  # where a human made the decision that set the status (ADR-20261006-c300)


class InvStatus(StrEnum):
    PROPOSED = "PROPOSED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class Scope(_Record):
    paths: list[str] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class Origin(_Record):
    type: Literal["prompt", "braindump", "manual", "import"]
    text: str = Field(max_length=2000)
    ref: str | None = None


class Verification(_Record):
    runner: str
    harness_path: str
    harness_sha256: str | None = Field(default=None, pattern=SHA256)
    assertion_sha256: str | None = Field(default=None, pattern=SHA256)


class Invariant(_Record):
    schema_version: Literal["1"] = "1"
    id: str = Field(pattern=INV_ID)
    title: str = Field(min_length=3, max_length=120)
    assertion: str = Field(min_length=10)
    scope: Scope
    status: InvStatus = InvStatus.PROPOSED
    origin: Origin
    verification: Verification
    adr_id: str | None = Field(default=None, pattern=ADR_ID)
    created_at: AwareDatetime = Field(default_factory=utcnow)
    approved_at: AwareDatetime | None = None
    approved_by: str | None = None
    superseded_by: str | None = Field(default=None, pattern=INV_ID)
    status_reason: str | None = None
    decided_via: Via | None = None  # None: decided in the terminal, before this field existed

    @model_validator(mode="after")
    def _status_requirements(self) -> Invariant:
        """Same rules as the schema's allOf (§10.1): fields a status needs must be non-null."""
        missing: list[str] = []
        if self.status == InvStatus.LOCKED:
            missing += [f for f in ("approved_at", "approved_by") if getattr(self, f) is None]
            missing += [
                f"verification.{f}"
                for f in ("harness_sha256", "assertion_sha256")
                if getattr(self.verification, f) is None
            ]
        elif self.status in (InvStatus.SUPERSEDED, InvStatus.REJECTED) and self.status_reason is None:
            # superseded_by may stay null: a pure retirement has no replacement (§11.1).
            missing.append("status_reason")
        if missing:
            raise ValueError(f"status {self.status.value} requires {', '.join(missing)}")
        return self


class DeadEnd(_Record):
    schema_version: Literal["1"] = "1"
    id: str = Field(pattern=DE_ID)
    scope: Scope
    approach: str = Field(min_length=10)
    failure_symptom: str = Field(max_length=1000)
    source: Literal["verifier", "braindump", "manual", "agent"]
    related_invariant: str | None = Field(default=None, pattern=INV_ID)
    status: Literal["ACTIVE", "RETIRED"] = "ACTIVE"
    retired_reason: str | None = None
    decided_via: Via | None = None
    created_at: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _retired_needs_reason(self) -> DeadEnd:
        if self.status == "RETIRED" and self.retired_reason is None:
            raise ValueError("status RETIRED requires retired_reason")
        return self
