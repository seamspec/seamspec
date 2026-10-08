"""Models and packaged JSON Schemas must agree (SPEC §9.4, §10)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from seamspec.core.models import DeadEnd, Invariant, InvStatus
from seamspec.core.schemas import load_schema, validation_errors

from .conftest import make_dead_end, make_invariant


def as_json(record) -> dict:
    return json.loads(record.model_dump_json())


@pytest.mark.parametrize("status", list(InvStatus))
def test_invariants_in_every_status_validate(status: InvStatus) -> None:
    inv = make_invariant(status=status)
    assert validation_errors("invariant", as_json(inv)) == []
    assert Invariant.model_validate(as_json(inv)) == inv


def test_dead_ends_validate() -> None:
    for de in (make_dead_end(), make_dead_end(status="RETIRED", retired_reason="Fixed upstream")):
        assert validation_errors("dead_end", as_json(de)) == []
        assert DeadEnd.model_validate(as_json(de)) == de


@pytest.mark.parametrize("via", ["terminal", "chat", None])
def test_decided_via_validates(via: str | None) -> None:
    """Where a human decided (ADR-20261006-c300); None is a record from before the field existed."""
    inv = make_invariant(status=InvStatus.LOCKED, decided_via=via)
    de = make_dead_end(status="RETIRED", retired_reason="Fixed upstream", decided_via=via)
    assert validation_errors("invariant", as_json(inv)) == [] and validation_errors("dead_end", as_json(de)) == []


def test_locked_with_null_approval_fails_both() -> None:
    data = as_json(make_invariant(status=InvStatus.LOCKED))
    data["approved_by"] = None
    assert any("approved_by" in e for e in validation_errors("invariant", data))
    with pytest.raises(ValidationError, match="approved_by"):
        Invariant.model_validate(data)


def test_locked_with_null_hash_fails_both() -> None:
    data = as_json(make_invariant(status=InvStatus.LOCKED))
    data["verification"]["harness_sha256"] = None
    assert validation_errors("invariant", data)
    with pytest.raises(ValidationError, match="harness_sha256"):
        Invariant.model_validate(data)


def test_superseded_may_have_no_replacement_but_needs_reason() -> None:
    data = as_json(make_invariant(status=InvStatus.SUPERSEDED))
    assert data["superseded_by"] is None
    assert validation_errors("invariant", data) == []
    data["status_reason"] = None
    assert validation_errors("invariant", data)
    with pytest.raises(ValidationError, match="status_reason"):
        Invariant.model_validate(data)


def test_retired_dead_end_needs_reason() -> None:
    data = as_json(make_dead_end())
    data["status"] = "RETIRED"
    assert validation_errors("dead_end", data)
    with pytest.raises(ValidationError, match="retired_reason"):
        DeadEnd.model_validate(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra_field=1),
        lambda d: d.update(id="inv_XYZ"),
        lambda d: d.update(adr_id="ADR-1"),
        lambda d: d.update(title="ab"),
        lambda d: d["scope"].update(paths=[]),
        lambda d: d["origin"].update(type="chat"),
        lambda d: d["verification"].update(harness_sha256="short"),
        lambda d: d.update(created_at="not a date"),
        lambda d: d.update(decided_via="email"),
    ],
)
def test_bad_invariants_fail_both(mutate) -> None:
    data = as_json(make_invariant())
    mutate(data)
    assert validation_errors("invariant", data), "JSON Schema accepted a bad record"
    with pytest.raises(ValidationError):
        Invariant.model_validate(data)


def test_naive_datetime_rejected_by_model() -> None:
    data = as_json(make_invariant())
    data["created_at"] = "2026-10-03T08:12:00"
    with pytest.raises(ValidationError):
        Invariant.model_validate(data)


def test_schema_ids_use_published_base() -> None:
    for name in ("invariant", "dead_end", "config"):
        assert load_schema(name)["$id"] == f"https://seamspec.github.io/schemas/v1/{name}.json"
