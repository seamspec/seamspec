"""The "many rules" variant (ADR-20261013-9d41, section 9).

Three agreed rules fit in a notes file and in anyone's head. A project a few months old has dozens.
Conditions G and H give every task 36 more agreed rules, about two small helper packages
(`src/common`, `src/shared`) that the task's requests never ask to change. The same 36, with the
same wording, go into the notes file (G) and into SeamSpec's ledger as locked rules with real
tests (H). Only the task's own rules are scored: the question is whether they still hold when
they are three among thirty-nine.

Each entry: id, package/module, title, the agreement in one sentence, then the names it imports and
the body of its test, once for Python (pytest) and once for TypeScript (vitest).
"""

# ruff: noqa: E501  (the table below keeps each rule's test on its own lines)
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .tasks import Rule

SCALE_DIR = Path(__file__).resolve().parents[1] / "scale"
PACKAGES = ("common", "shared")


@dataclass(frozen=True)
class Extra:
    id: str
    module: str  # "common/ids"
    title: str
    assertion: str
    py: tuple[str, str]  # (names to import, test body)
    ts: tuple[str, str]


def _x(id: str, module: str, title: str, assertion: str, py: tuple[str, str], ts: tuple[str, str]) -> Extra:
    return Extra(id, module, title, assertion, py, ts)


RAISES = "with pytest.raises({exc}):\n        {call}"

EXTRAS: tuple[Extra, ...] = (
    # --- common/ids ---
    _x("ids_lowercase", "common/ids", "Record ids are lowercase",
       "make_id always returns the prefix in lowercase, whatever case it was given.",
       ("make_id", 'assert make_id("ORD", 7) == "ord-000007"'),
       ("makeId", 'expect(makeId("ORD", 7)).toBe("ord-000007");')),
    _x("ids_six_digits", "common/ids", "Id numbers are padded to six digits",
       "The number in an id is always written with exactly six digits, padded with zeros.",
       ("make_id", 'assert make_id("job", 42).split("-")[1] == "000042"\n    assert make_id("job", 999999).endswith("-999999")'),
       ("makeId", 'expect(makeId("job", 42).split("-")[1]).toBe("000042");\n  expect(makeId("job", 999999).endsWith("-999999")).toBe(true);')),
    _x("ids_letters_only", "common/ids", "An id prefix is letters only",
       "make_id refuses a prefix that contains anything but letters.",
       ("make_id", 'for bad in ("or1", "", "a-b", "a b"):\n        with pytest.raises(ValueError):\n            make_id(bad, 1)'),
       ("makeId", 'for (const bad of ["or1", "", "a-b", "a b"]) expect(() => makeId(bad, 1)).toThrow();')),
    _x("ids_round_trip", "common/ids", "parse_id reverses make_id",
       "Parsing an id that make_id produced gives back the lowercase prefix and the number.",
       ("make_id, parse_id", 'for number in (0, 1, 42, 999999):\n        assert parse_id(make_id("Inv", number)) == ("inv", number)'),
       ("makeId, parseId", 'for (const n of [0, 1, 42, 999999]) expect(parseId(makeId("Inv", n))).toEqual(["inv", n]);')),
    _x("ids_malformed", "common/ids", "A malformed id is an error, never a guess",
       "parse_id raises for anything that is not lowercase letters, a dash and six digits.",
       ("parse_id", 'for bad in ("ord-12", "ORD-000001", "ord000001", "ord-0000001", "-000001", "ord-00000a"):\n        with pytest.raises(ValueError):\n            parse_id(bad)'),
       ("parseId", 'for (const bad of ["ord-12", "ORD-000001", "ord000001", "ord-0000001", "-000001", "ord-00000a"])\n    expect(() => parseId(bad)).toThrow();')),
    _x("ids_range", "common/ids", "Id numbers stay between 0 and 999999",
       "make_id refuses a number below 0 or above 999999.",
       ("make_id", 'for bad in (-1, 1_000_000):\n        with pytest.raises(ValueError):\n            make_id("ord", bad)'),
       ("makeId", 'for (const bad of [-1, 1000000]) expect(() => makeId("ord", bad)).toThrow();')),
    # --- common/config ---
    _x("config_prefix", "common/config", "Settings come only from APP_ variables",
       "load ignores every environment variable whose name does not start with APP_.",
       ("DEFAULTS, load", 'assert load({"BATCH_SIZE": "5", "REGION": "us", "PATH": "/bin"}) == DEFAULTS'),
       ("DEFAULTS, load", 'expect(load({ BATCH_SIZE: "5", REGION: "us", PATH: "/bin" })).toEqual({ ...DEFAULTS });')),
    _x("config_unknown", "common/config", "An unknown APP_ setting is an error",
       "load raises for an APP_ variable that is not a known setting, so a typo is never ignored.",
       ("load", 'with pytest.raises(KeyError):\n        load({"APP_COLOUR": "red"})'),
       ("load", 'expect(() => load({ APP_COLOUR: "red" })).toThrow();')),
    _x("config_booleans", "common/config", "Boolean settings accept only true or false",
       "A boolean setting is true for the text true, false for false, and an error for anything else.",
       ("load", 'assert load({"APP_VERBOSE": "true"})["verbose"] is True\n    assert load({"APP_VERBOSE": "false"})["verbose"] is False\n    for bad in ("yes", "1", "TRUE", ""):\n        with pytest.raises(ValueError):\n            load({"APP_VERBOSE": bad})'),
       ("load", 'expect(load({ APP_VERBOSE: "true" }).verbose).toBe(true);\n  expect(load({ APP_VERBOSE: "false" }).verbose).toBe(false);\n  for (const bad of ["yes", "1", "TRUE", ""]) expect(() => load({ APP_VERBOSE: bad })).toThrow();')),
    _x("config_positive", "common/config", "Numeric settings must be positive",
       "A numeric setting of zero or less is an error.",
       ("load", 'assert load({"APP_BATCH_SIZE": "8"})["batch_size"] == 8\n    for bad in ("0", "-3"):\n        with pytest.raises(ValueError):\n            load({"APP_BATCH_SIZE": bad})'),
       ("load", 'expect(load({ APP_BATCH_SIZE: "8" }).batch_size).toBe(8);\n  for (const bad of ["0", "-3"]) expect(() => load({ APP_BATCH_SIZE: bad })).toThrow();')),
    _x("config_trimmed", "common/config", "Setting values are trimmed",
       "Spaces before and after a setting's value are removed before it is used.",
       ("load", 'assert load({"APP_REGION": "  us "})["region"] == "us"\n    assert load({"APP_MAX_ITEMS": " 25 "})["max_items"] == 25'),
       ("load", 'expect(load({ APP_REGION: "  us " }).region).toBe("us");\n  expect(load({ APP_MAX_ITEMS: " 25 " }).max_items).toBe(25);')),
    _x("config_defaults_kept", "common/config", "Loading settings never changes the defaults",
       "After load returns, the defaults are what they were, and the next load starts from them again.",
       ("DEFAULTS, load", 'before = dict(DEFAULTS)\n    load({"APP_REGION": "us", "APP_BATCH_SIZE": "9"})\n    assert DEFAULTS == before and load({}) == before'),
       ("DEFAULTS, load", 'const before = { ...DEFAULTS };\n  load({ APP_REGION: "us", APP_BATCH_SIZE: "9" });\n  expect({ ...DEFAULTS }).toEqual(before);\n  expect(load({})).toEqual(before);')),
    # --- common/logfmt ---
    _x("log_one_line", "common/logfmt", "A log line is one line",
       "line never returns text with a line break in it, even when the message has one.",
       ("line", 'assert "\\n" not in line("info", "first\\nsecond", detail="a\\nb")'),
       ("line", 'expect(line("info", "first\\nsecond", { detail: "a\\nb" })).not.toContain("\\n");')),
    _x("log_sorted_json", "common/logfmt", "Log lines are JSON with sorted keys",
       "line returns a JSON object whose keys are in alphabetical order.",
       ("line", 'import json\n\n    record = json.loads(line("info", "started", zone="b", attempt=2))\n    assert list(record) == sorted(record) and record["attempt"] == 2'),
       ("line", 'const record = JSON.parse(line("info", "started", { zone: "b", attempt: 2 }));\n  expect(Object.keys(record)).toEqual(Object.keys(record).sort());\n  expect(record.attempt).toBe(2);')),
    _x("log_levels", "common/logfmt", "Log levels are upper-case and from a fixed list",
       "line writes the level in capitals and refuses a level that is not DEBUG, INFO, WARNING or ERROR.",
       ("line", 'assert \'"level": "INFO"\' in line("info", "x")\n    with pytest.raises(ValueError):\n        line("trace", "x")'),
       ("line", 'expect(JSON.parse(line("info", "x")).level).toBe("INFO");\n  expect(() => line("trace", "x")).toThrow();')),
    _x("log_masked", "common/logfmt", "Secret fields are masked in log lines",
       "A field named password, token or secret is written as *** and its value never appears.",
       ("line", 'text = line("info", "login", password="hunter2", Token="abc123", user="ada")\n    assert "hunter2" not in text and "abc123" not in text and \'"user": "ada"\' in text'),
       ("line", 'const text = line("info", "login", { password: "hunter2", Token: "abc123", user: "ada" });\n  expect(text).not.toContain("hunter2");\n  expect(text).not.toContain("abc123");\n  expect(JSON.parse(text).user).toBe("ada");')),
    _x("log_reserved", "common/logfmt", "Extra fields never replace the level or the message",
       "A field named level or message is ignored: the line keeps the level and message it was called with.",
       ("line", 'import json\n\n    record = json.loads(line("error", "disk full", **{"level": "debug", "message": "fine"}))\n    assert record["level"] == "ERROR" and record["message"] == "disk full"'),
       ("line", 'const record = JSON.parse(line("error", "disk full", { level: "debug", message: "fine" }));\n  expect(record.level).toBe("ERROR");\n  expect(record.message).toBe("disk full");')),
    _x("log_ascii", "common/logfmt", "Log lines are plain ASCII",
       "line escapes every character outside ASCII, so the collector never sees raw accented text.",
       ("line", 'assert line("info", "café ☕", city="Zürich").isascii()'),
       ("line", 'expect(/^[\\x00-\\x7f]*$/.test(line("info", "café ☕", { city: "Zürich" }))).toBe(true);')),
    # --- shared/paging ---
    _x("page_from_one", "shared/paging", "Pages are numbered from 1",
       "Page 1 is the first page, and a page number below 1 is an error.",
       ("page", 'assert page(list("abcde"), 1, 2)["items"] == ["a", "b"]\n    with pytest.raises(ValueError):\n        page(list("abcde"), 0, 2)'),
       ("page", 'expect(page([..."abcde"], 1, 2).items).toEqual(["a", "b"]);\n  expect(() => page([..."abcde"], 0, 2)).toThrow();')),
    _x("page_cap", "shared/paging", "A page holds at most 100 items",
       "Whatever size is asked for, a page never holds more than 100 items, and it reports the size it used.",
       ("page", 'result = page(list(range(500)), 1, 250)\n    assert len(result["items"]) == 100 and result["size"] == 100'),
       ("page", 'const result = page([...Array(500).keys()], 1, 250);\n  expect(result.items.length).toBe(100);\n  expect(result.size).toBe(100);')),
    _x("page_past_end", "shared/paging", "A page past the end is empty, not an error",
       "Asking for a page after the last one returns no items and does not raise.",
       ("page", 'assert page(list("abc"), 9, 2)["items"] == []'),
       ("page", 'expect(page([..."abc"], 9, 2).items).toEqual([]);')),
    _x("page_total", "shared/paging", "Every page reports the total number of items",
       "The total on every page is the length of the whole list, not of the page.",
       ("page", 'items = list(range(45))\n    assert {page(items, n, 20)["total"] for n in (1, 2, 3, 4)} == {45}'),
       ("page", 'const items = [...Array(45).keys()];\n  for (const n of [1, 2, 3, 4]) expect(page(items, n, 20).total).toBe(45);')),
    _x("page_size_min", "shared/paging", "A page size below 1 is an error",
       "page refuses a size of zero or less.",
       ("page", 'for bad in (0, -5):\n        with pytest.raises(ValueError):\n            page(list("abc"), 1, bad)'),
       ("page", 'for (const bad of [0, -5]) expect(() => page([..."abc"], 1, bad)).toThrow();')),
    _x("page_order", "shared/paging", "Paging never changes the order of items",
       "Reading the pages one after another gives the original list, in its original order.",
       ("page", 'items = [5, 3, 9, 1, 7, 2, 8]\n    seen = [x for n in (1, 2, 3) for x in page(items, n, 3)["items"]]\n    assert seen == items'),
       ("page", 'const items = [5, 3, 9, 1, 7, 2, 8];\n  const seen = [1, 2, 3].flatMap((n) => page(items, n, 3).items);\n  expect(seen).toEqual(items);')),
    # --- shared/textfmt ---
    _x("slug_charset", "shared/textfmt", "Slugs are lowercase letters, digits and hyphens",
       "slugify returns only lowercase letters, digits and single hyphens.",
       ("slugify", 'import re\n\n    for text in ("Hello, World!", "Q3 Report (final)", "a  b__c"):\n        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slugify(text)), text'),
       ("slugify", 'for (const text of ["Hello, World!", "Q3 Report (final)", "a  b__c"])\n    expect(slugify(text)).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);')),
    _x("slug_edges", "shared/textfmt", "Slugs never start or end with a hyphen",
       "Punctuation or spaces at either end of the text leave no hyphen at either end of the slug.",
       ("slugify", 'assert slugify("  --Hello World!  ") == "hello-world"'),
       ("slugify", 'expect(slugify("  --Hello World!  ")).toBe("hello-world");')),
    _x("slug_empty", "shared/textfmt", "Text with nothing usable gives an empty slug",
       "slugify returns an empty string for empty text and for text made only of symbols.",
       ("slugify", 'assert slugify("") == "" and slugify("!!! ???") == ""'),
       ("slugify", 'expect(slugify("")).toBe("");\n  expect(slugify("!!! ???")).toBe("");')),
    _x("truncate_limit", "shared/textfmt", "Truncated text is never longer than the limit",
       "truncate never returns more characters than the limit it was given.",
       ("truncate", 'text = "The quick brown fox jumps over the lazy dog"\n    assert all(len(truncate(text, n)) <= n for n in range(1, 60))'),
       ("truncate", 'const text = "The quick brown fox jumps over the lazy dog";\n  for (let n = 1; n < 60; n++) expect(truncate(text, n).length).toBeLessThanOrEqual(n);')),
    _x("truncate_ellipsis", "shared/textfmt", "Cut text ends with an ellipsis; uncut text is unchanged",
       "Text that had to be cut ends with the character …, and text that fits is returned as it is.",
       ("truncate", 'assert truncate("abcdefghij", 5) == "abcd…" and truncate("abc", 5) == "abc"'),
       ("truncate", 'expect(truncate("abcdefghij", 5)).toBe("abcd…");\n  expect(truncate("abc", 5)).toBe("abc");')),
    _x("truncate_spaces", "shared/textfmt", "Truncate collapses runs of whitespace",
       "Line breaks, tabs and repeated spaces become single spaces before the text is measured.",
       ("truncate", 'assert truncate("a \\n\\t b    c", 20) == "a b c"'),
       ("truncate", 'expect(truncate("a \\n\\t b    c", 20)).toBe("a b c");')),
    # --- shared/timefmt ---
    _x("time_utc", "shared/timefmt", "Timestamps are written in UTC and end with Z",
       "to_iso writes the time in UTC as YYYY-MM-DDTHH:MM:SS followed by Z.",
       ("to_iso", 'assert to_iso(0) == "1970-01-01T00:00:00Z" and to_iso(1_700_000_000) == "2023-11-14T22:13:20Z"'),
       ("toIso", 'expect(toIso(0)).toBe("1970-01-01T00:00:00Z");\n  expect(toIso(1700000000)).toBe("2023-11-14T22:13:20Z");')),
    _x("time_whole_seconds", "shared/timefmt", "Timestamps carry no fractions of a second",
       "to_iso drops any fraction of a second: 1.999 seconds is written as second 1, never as second 2.",
       ("to_iso", 'assert to_iso(1.999) == "1970-01-01T00:00:01Z"'),
       ("toIso", 'expect(toIso(1.999)).toBe("1970-01-01T00:00:01Z");')),
    _x("time_round_trip", "shared/timefmt", "from_iso reverses to_iso",
       "Reading a timestamp that to_iso wrote gives back the same whole second.",
       ("from_iso, to_iso", 'for seconds in (0, 59, 86_400, 1_700_000_000):\n        assert from_iso(to_iso(seconds)) == seconds'),
       ("fromIso, toIso", 'for (const s of [0, 59, 86400, 1700000000]) expect(fromIso(toIso(s))).toBe(s);')),
    _x("time_needs_z", "shared/timefmt", "A timestamp without Z is rejected",
       "from_iso raises for a timestamp that does not end with Z: local times are never guessed.",
       ("from_iso", 'for bad in ("2023-11-14T22:13:20", "2023-11-14T22:13:20+01:00", "2023-11-14"):\n        with pytest.raises(ValueError):\n            from_iso(bad)'),
       ("fromIso", 'for (const bad of ["2023-11-14T22:13:20", "2023-11-14T22:13:20+01:00", "2023-11-14"])\n    expect(() => fromIso(bad)).toThrow();')),
    _x("duration_seconds", "shared/timefmt", "Durations under a minute are shown in seconds",
       "duration_text writes a duration below 60 seconds as the number followed by s.",
       ("duration_text", 'assert duration_text(0) == "0s" and duration_text(45) == "45s" and duration_text(59) == "59s"'),
       ("durationText", 'expect(durationText(0)).toBe("0s");\n  expect(durationText(45)).toBe("45s");\n  expect(durationText(59)).toBe("59s");')),
    _x("duration_hours", "shared/timefmt", "Durations of an hour or more read like 1h 05m",
       "From one hour up, duration_text writes hours and two-digit minutes; below an hour, minutes alone.",
       ("duration_text", 'assert duration_text(3900) == "1h 05m" and duration_text(7200) == "2h 00m" and duration_text(600) == "10m"'),
       ("durationText", 'expect(durationText(3900)).toBe("1h 05m");\n  expect(durationText(7200)).toBe("2h 00m");\n  expect(durationText(600)).toBe("10m");')),
)  # fmt: skip

assert len(EXTRAS) == 36 and len({e.id for e in EXTRAS}) == 36


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def _names_for_typescript(text: str) -> str:
    for name in ("make_id", "parse_id", "to_iso", "from_iso", "duration_text"):
        text = text.replace(name, _camel(name))
    return text


def assertion(extra: Extra, language: str) -> str:
    """The agreement as a person would write it for that codebase: TypeScript names are camelCase."""
    return extra.assertion if language == "python" else _names_for_typescript(extra.assertion)


def title(extra: Extra, language: str) -> str:
    return extra.title if language == "python" else _names_for_typescript(extra.title)


def test_source(extra: Extra, language: str) -> str:
    """One self-contained test file per extra rule (SeamSpec keeps one test file per rule)."""
    package, module = extra.module.split("/")
    if language == "python":
        names, body = extra.py
        return (
            f'"""Rule: {extra.title}."""\n\n'
            "import sys\nfrom pathlib import Path\n\n"
            'sys.path.insert(0, str(next(p / "src" for p in Path(__file__).resolve().parents'
            ' if (p / "src/common").is_dir())))\n\n'
            "import pytest  # noqa: E402, F401\n\n"
            f"from {package}.{module} import {names}  # noqa: E402\n\n\n"
            f"def test_{extra.id}() -> None:\n    {body}\n"
        )
    names, body = extra.ts
    return (
        f"// Rule: {title(extra, language)}.\n"
        'import { expect, test } from "vitest";\n'
        f'import {{ {names} }} from "{{{{SRC}}}}/{package}/{module}";\n\n'
        f"test({json.dumps(title(extra, language))}, () => {{\n  {body}\n}});\n"
    )


def rules(language: str) -> list[Rule]:
    """The extra agreements as benchmark rules. `file` is the test's name; its code comes from `test_source`."""
    suffix = "py" if language == "python" else "ts"
    return [
        Rule(
            id=e.id,
            title=title(e, language),
            assertion=assertion(e, language),
            scope=(f"src/{e.module}.{suffix}",),
            file=f"test_{e.id}.py" if language == "python" else f"{e.id}.test.ts",
        )
        for e in EXTRAS
    ]


def install_code(language: str, work: Path) -> None:
    """Copy the two helper packages into the working copy's `src/`."""
    import shutil

    for package in PACKAGES:
        shutil.copytree(SCALE_DIR / language / package, work / "src" / package)
