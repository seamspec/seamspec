"""BRAINDUMP.md (SPEC §13, ADR-20261013-d9e4): the person's scratchpad, sorted by the agent into
proposals that still wait for review. SeamSpec parses, remembers, and tidies only when asked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seamspec.adapters import claude
from seamspec.cli import app
from seamspec.core import adr, braindump, lifecycle
from seamspec.core.config import load_config
from seamspec.core.store import Store
from seamspec.installers import scaffold

from .conftest import git
from .test_lifecycle import propose

runner = CliRunner()
MARKER = "<!-- seamspec:processed -->"

NOTES = """# BRAINDUMP.md
<!-- a comment, ignored -->

- Tenant isolation must not leak if `org_id` is missing — reject with 400.
  Seen once in staging.
* [x] Look at how Stripe handles idempotent webhooks
1. Error format should be RFC 7807 problem details everywhere.

Tried caching JWT validation in a global dict — leaked across tenants.
Don't.

```python
# a comment inside code, not a heading
- not a list item either
```

## Later
- TODO benchmark Redis pipelining under load.

<!-- seamspec:processed -->
## Processed (managed by SeamSpec)
- `bd_00000000` → below the marker: never read
"""


@pytest.fixture
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE", "1")


def test_parse_items_follows_the_rules_of_13_5() -> None:
    items = braindump.parse_items(NOTES, MARKER)
    texts = [i.text for i in items]
    assert texts == [
        "Tenant isolation must not leak if `org_id` is missing — reject with 400.\nSeen once in staging.",
        "Look at how Stripe handles idempotent webhooks",
        "Error format should be RFC 7807 problem details everywhere.",
        "Tried caching JWT validation in a global dict — leaked across tenants.\nDon't.",
        "```python\n# a comment inside code, not a heading\n- not a list item either\n```",
        "TODO benchmark Redis pipelining under load.",
    ]
    assert all(i.id.startswith("bd_") and len(i.id) == 11 for i in items)
    # Reflowing a note keeps its id; changing its words makes a new item.
    assert braindump.item_id("Error  format should be\nRFC 7807") == braindump.item_id(
        "error format should be rfc 7807"
    )
    assert braindump.item_id("Error format should be RFC 9457") != braindump.item_id("Error format should be RFC 7807")


def project(tmp_path: Path) -> Store:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / ".git").mkdir()
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    (tmp_path / "BRAINDUMP.md").write_text(NOTES)
    return Store(tmp_path)


def test_init_creates_the_scratchpad_once_and_git_ignored(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    report = scaffold.init(tmp_path)
    text = (tmp_path / "BRAINDUMP.md").read_text()
    assert MARKER in text and braindump.parse_items(text, MARKER) == []  # the example is inside a comment
    assert dict(report.actions)["BRAINDUMP.md"] == "created (git-ignored)"
    assert "\nBRAINDUMP.md\n" in (tmp_path / ".gitignore").read_text()
    # A team that shares it removes the ignore line: rerunning init never adds it back.
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(gitignore.read_text().replace("BRAINDUMP.md\n", ""))
    (tmp_path / "BRAINDUMP.md").write_text("- my own note\n")
    assert dict(scaffold.init(tmp_path).actions)["BRAINDUMP.md"] == "kept"
    assert "BRAINDUMP.md" not in gitignore.read_text() and (tmp_path / "BRAINDUMP.md").read_text() == "- my own note\n"


def test_each_record_made_from_a_note_marks_it_sorted(tmp_path: Path, human: None) -> None:
    store = project(tmp_path)
    cfg = load_config(tmp_path)
    notes = {i.text.split()[0]: i for i in braindump.pending(store, "BRAINDUMP.md", MARKER)}
    tenant, stripe, rfc, tried, todo = notes["Tenant"], notes["Look"], notes["Error"], notes["Tried"], notes["TODO"]

    rule = propose(tmp_path, origin_type="braindump", origin_ref=tenant.id, origin_text=tenant.text)["id"]
    dead = lifecycle.log_dead_end(store, cfg, scope_paths=["src/**"], approach="A global dict cache for JWTs",
                                  failure_symptom="Leaked across tenants.", origin_ref=tried.id)["id"]  # fmt: skip
    decision = lifecycle.propose_decision(
        store, cfg, title="RFC 7807 errors", context="Clients parse errors.", decision="Use RFC 7807 problem details.",
        consequences=[], scope_paths=["src/**"], origin_text=rfc.text, origin_ref=rfc.id,
    )["adr_id"]  # fmt: skip
    dismissals = [{"item_id": stripe.id, "as": "exploration"}, {"item_id": todo.id, "as": "todo"}]
    assert braindump.dismiss(store, "BRAINDUMP.md", MARKER, dismissals) == [stripe.id, todo.id]

    left = braindump.pending(store, "BRAINDUMP.md", MARKER)
    assert [i.text.split()[0] for i in left] == ["```python"]
    done = braindump.state(store)
    assert done[tenant.id]["as"] == "invariant" and done[tenant.id]["ref"] == rule
    assert done[tried.id] == {**done[tried.id], "as": "dead_end", "ref": dead}
    assert done[tried.id]["preview"] == " ".join(tried.text.split())[:80]  # the note's words, not the rewording
    assert store.get(dead).origin_ref == tried.id and store.get(dead).source == "braindump"
    assert done[rfc.id]["ref"] == decision and adr.get(store, decision).status == "PROPOSED"
    assert f"braindump item `{rfc.id}`" in adr.get(store, decision).body
    assert done[stripe.id]["as"] == "exploration" and done[todo.id]["as"] == "todo"
    assert (tmp_path / "BRAINDUMP.md").read_text() == NOTES  # nothing above the marker was touched
    with pytest.raises(ValueError, match="todo, exploration"):
        braindump.dismiss(store, "BRAINDUMP.md", MARKER, [{"item_id": left[0].id, "as": "invariant"}])
    with pytest.raises(KeyError):
        braindump.dismiss(store, "BRAINDUMP.md", MARKER, [{"item_id": stripe.id, "as": "todo"}])  # not pending


def test_secrets_in_a_note_never_reach_a_committed_record(tmp_path: Path, human: None) -> None:
    store = project(tmp_path)
    cfg = load_config(tmp_path)
    key = "sk-" + "a" * 30
    out = lifecycle.log_dead_end(store, cfg, scope_paths=["src/**"], approach=f"Called the API with {key} inline",
                                 failure_symptom=f"Rate limited; token={key}", origin_ref="bd_12345678")  # fmt: skip
    text = (tmp_path / ".seamspec/dead_ends" / f"{out['id']}.json").read_text()
    assert key not in text and "[REDACTED]" in text


def test_review_accepts_or_rejects_a_proposed_decision(tmp_path: Path, human: None, monkeypatch) -> None:
    store = project(tmp_path)
    cfg = load_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    one = lifecycle.propose_decision(store, cfg, title="One", context="c", decision="Do one.", consequences=[],
                                     scope_paths=["src/**"], origin_text="x")["adr_id"]  # fmt: skip
    two = lifecycle.propose_decision(store, cfg, title="Two", context="c", decision="Do two.", consequences=[],
                                     scope_paths=["src/**"], origin_text="x")["adr_id"]  # fmt: skip
    status = json.loads(runner.invoke(app, ["status", "--json"]).output)
    assert status["awaiting_review"] == 2
    out = runner.invoke(app, ["review"], input="a\nr\n")
    assert "2 proposed decision(s)" in out.output and "Do one." in out.output
    first, second = sorted((one, two), key=lambda i: out.output.index(f"· {i}"))  # shown in id order
    assert adr.get(store, first).status == "ACCEPTED" and adr.get(store, second).status == "REJECTED"
    events = [json.loads(line)["event"] for line in (store.local / "journal.jsonl").read_text().splitlines()
              if "decision_" in line]  # fmt: skip
    assert events == ["decision_accepted", "decision_rejected"]
    with pytest.raises(lifecycle.LifecycleError, match="not PROPOSED"):
        lifecycle.decide_decision(store, first, accept=False)


def _decision(store: Store, cfg, title: str) -> dict:
    return lifecycle.propose_decision(store, cfg, title=title, context="c", decision=f"Do {title}.", consequences=[],
                                      scope_paths=["src/**"], origin_text="x")  # fmt: skip


def test_decisions_count_toward_the_review_cap(tmp_path: Path) -> None:
    """One long plan once became 20 proposed decisions in a single sort (hands-on test, 2026-10-14)."""
    store = project(tmp_path)
    cfg = load_config(tmp_path)
    cap = cfg.proposals.max_pending
    made = [_decision(store, cfg, f"d{n}") for n in range(cap)]
    assert all("adr_id" in m for m in made)
    full = _decision(store, cfg, "one too many")
    assert full["error"] == "queue_full" and full["pending"] == cap
    assert len(adr.load_all(store)) == cap  # nothing written
    assert propose(tmp_path)["error"] == "queue_full"  # rules wait behind the same queue


def test_review_rejects_the_rest_of_a_pile_of_decisions(tmp_path: Path, human: None, monkeypatch) -> None:
    store = project(tmp_path)
    cfg = load_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    ids = [_decision(store, cfg, f"d{n}")["adr_id"] for n in range(4)]
    out = runner.invoke(app, ["review"], input="a\nx\ny\n")
    assert out.exit_code == 0, out.output
    assert "[x] reject this and the 3 after it" in out.output and "Reject all 3?" in out.output
    shown = sorted(ids, key=out.output.index)  # review order: by id
    assert [adr.get(store, i).status for i in shown] == ["ACCEPTED", "REJECTED", "REJECTED", "REJECTED"]
    assert "[x]" not in runner.invoke(app, ["review"]).output  # nothing left


def test_rejecting_the_rest_asks_first(tmp_path: Path, human: None, monkeypatch) -> None:
    store = project(tmp_path)
    cfg = load_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    ids = [_decision(store, cfg, f"d{n}")["adr_id"] for n in range(2)]
    runner.invoke(app, ["review"], input="x\nn\ns\n")
    assert {adr.get(store, i).status for i in ids} == {"PROPOSED"}


def test_session_start_nudges_once_per_change(tmp_path: Path) -> None:
    store = project(tmp_path)
    cfg = load_config(tmp_path)
    first = claude._braindump_nudge(store, cfg, "startup")
    assert first and "BRAINDUMP.md has 6 new note(s)" in first and "Don't sort them without a yes" in first
    assert claude._braindump_nudge(store, cfg, "startup") is None  # nothing new since the last nudge
    assert claude._braindump_nudge(store, cfg, "compact") is None  # never mid-task
    (tmp_path / "BRAINDUMP.md").write_text(NOTES.replace("## Later", "- A brand new note.\n\n## Later"))
    assert "7 new note(s)" in claude._braindump_nudge(store, cfg, "clear")
    out = claude.session_start({"source": "startup"}, store, cfg)
    assert out is None  # no rules, nothing new: silence is the default
    config = tmp_path / ".seamspec/config.toml"
    assert 'nudge = "ask"' in config.read_text()
    config.write_text(config.read_text().replace('nudge = "ask"', 'nudge = "off"'))
    (tmp_path / "BRAINDUMP.md").write_text(NOTES + "- one more\n")
    assert claude._braindump_nudge(store, load_config(tmp_path), "startup") is None


def test_offer_comes_back_when_the_code_changes(tmp_path: Path) -> None:
    """The first offer went unanswered in a chat that started with a task; the notes waited for code
    that then appeared (hands-on test, 2026-10-14)."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    git(tmp_path, "init", "-q", "-b", "main")
    scaffold.init(tmp_path, auto_run=True, actor="Maya <maya@example.com>")
    (tmp_path / "BRAINDUMP.md").write_text(NOTES)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    store, cfg = Store(tmp_path), load_config(tmp_path)
    assert claude._braindump_nudge(store, cfg, "startup")
    assert claude._braindump_nudge(store, cfg, "startup") is None  # same notes, same code
    (tmp_path / "cart.py").write_text("class Cart: ...\n")
    assert claude._braindump_nudge(store, cfg, "startup")  # the code the notes wait for exists now
    assert claude._braindump_nudge(store, cfg, "startup") is None


def test_drain_command_lists_and_tidy_moves_sorted_notes(tmp_path: Path, human: None, monkeypatch) -> None:
    store = project(tmp_path)
    monkeypatch.chdir(tmp_path)
    listed = runner.invoke(app, ["drain"])
    assert "6 note(s) not sorted yet" in listed.output
    pending = json.loads(runner.invoke(app, ["drain", "--json"]).output)["pending"]
    todo = next(p for p in pending if p["text"].startswith("TODO"))
    braindump.dismiss(store, "BRAINDUMP.md", MARKER, [{"item_id": todo["id"], "as": "todo"}])

    tidied = runner.invoke(app, ["drain", "--tidy"])
    assert tidied.exit_code == 0 and "Moved 1 sorted note(s)" in tidied.output
    text = (tmp_path / "BRAINDUMP.md").read_text()
    human_part, managed = text.split(MARKER)
    assert "TODO benchmark" not in human_part and f"`{todo['id']}` → dismissed (todo)" in managed
    assert "Tenant isolation must not leak" in human_part and "## Later" in human_part  # the rest untouched
    assert len(json.loads(runner.invoke(app, ["drain", "--json"]).output)["pending"]) == 5
    monkeypatch.delenv("SEAMSPEC_ALLOW_NONINTERACTIVE_APPROVE")
    assert runner.invoke(app, ["drain", "--tidy"]).exit_code == 1  # an agent's shell: it's the person's file


def test_drain_dismiss_sets_notes_aside_without_mcp(tmp_path: Path, monkeypatch) -> None:
    """Without the tools, an agent could list notes but not set any aside (hands-on test, 2026-10-14)."""
    project(tmp_path)
    monkeypatch.chdir(tmp_path)
    pending = json.loads(runner.invoke(app, ["drain", "--json"]).output)["pending"]
    todo = next(p["id"] for p in pending if p["text"].startswith("TODO"))
    idea = next(p["id"] for p in pending if p["id"] != todo)
    out = runner.invoke(app, ["drain", "--dismiss", f"{todo}=todo", "--dismiss", f"{idea}=exploration"])
    assert out.exit_code == 0 and "Set aside 2 note(s)" in out.output
    left = json.loads(runner.invoke(app, ["drain", "--json"]).output)["pending"]
    assert len(left) == len(pending) - 2 and todo not in {p["id"] for p in left}
    assert runner.invoke(app, ["drain", "--dismiss", f"{todo}=todo"]).exit_code == 1  # no longer pending
    assert runner.invoke(app, ["drain", "--dismiss", f"{left[0]['id']}=rule"]).exit_code == 1
    assert runner.invoke(app, ["drain", "--dismiss", left[0]["id"]]).exit_code == 1


def test_braindump_tools_over_mcp(tmp_path: Path, monkeypatch) -> None:
    import anyio
    from mcp.client import Client

    from seamspec.mcp_server import mcp

    project(tmp_path)
    monkeypatch.setenv("SEAMSPEC_ROOT", str(tmp_path))

    async def call(name: str, args: dict):
        async with Client(mcp) as client:
            result = await client.call_tool(name, args)
            return json.loads(result.content[0].text)

    pending = anyio.run(call, "braindump_pending", {})["pending"]
    todo = next(p for p in pending if p["text"].startswith("TODO"))["id"]
    after = anyio.run(call, "braindump_pending", {"dismiss": {todo: "todo"}})
    assert after["dismissed"] == [todo] and len(after["pending"]) == 5
    args = {"title": "RFC 7807", "context": "c", "decision": "Use it.", "consequences": [],
            "scope_paths": ["src/**"], "origin_text": "x"}  # fmt: skip
    made = anyio.run(call, "propose_decision", args)
    assert made["status"] == "PROPOSED" and made["adr_id"].startswith("ADR-")


# --- planned rules: notes whose code doesn't exist yet (ADR-20261014-5e3a) ------------------------------


def _plan(store: Store, text_start: str) -> str:
    note = next(i for i in braindump.pending(store, "BRAINDUMP.md", MARKER) if i.text.startswith(text_start))
    braindump.dismiss(store, "BRAINDUMP.md", MARKER, [{"item_id": note.id, "as": "planned"}])
    return note.id


def test_a_planned_note_is_shown_to_the_agent_until_it_becomes_a_rule(tmp_path: Path, human: None) -> None:
    store = project(tmp_path)
    cfg = load_config(tmp_path)
    planned = _plan(store, "Tenant isolation")
    assert planned not in {i.id for i in braindump.pending(store, "BRAINDUMP.md", MARKER)}
    assert [i.id for i in braindump.planned(store, "BRAINDUMP.md", MARKER)] == [planned]

    summary = claude.session_start({"source": "startup"}, store, cfg)["hookSpecificOutput"]["additionalContext"]
    assert braindump.PLANNED_HEADING in summary and f"- {planned}: Tenant isolation must not leak" in summary

    rule = propose(tmp_path, origin_type="braindump", origin_ref=planned, origin_text="Tenants never leak.")["id"]
    assert braindump.planned(store, "BRAINDUMP.md", MARKER) == []  # it became that rule
    entry = braindump.state(store)[planned]
    assert entry["as"] == "invariant" and entry["ref"] == rule
    assert entry["preview"].startswith("Tenant isolation must not leak")  # the note's words


def test_deleting_the_note_drops_the_plan_and_tidy_keeps_it(tmp_path: Path, human: None, monkeypatch) -> None:
    store = project(tmp_path)
    planned = _plan(store, "Tenant isolation")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["drain", "--tidy"]).exit_code == 0
    assert "Tenant isolation must not leak" in (tmp_path / "BRAINDUMP.md").read_text().split(MARKER)[0]
    assert [i.id for i in braindump.planned(store, "BRAINDUMP.md", MARKER)] == [planned]

    text = (tmp_path / "BRAINDUMP.md").read_text()
    start = text.index("- Tenant isolation")
    end = text.index("* [x] Look at")
    (tmp_path / "BRAINDUMP.md").write_text(text[:start] + text[end:])
    assert braindump.planned(store, "BRAINDUMP.md", MARKER) == []


def test_planned_rules_in_status_drain_context_and_get_constraints(tmp_path: Path, monkeypatch) -> None:
    import anyio
    from mcp.client import Client

    from seamspec.mcp_server import mcp

    project(tmp_path)
    monkeypatch.chdir(tmp_path)
    pending = json.loads(runner.invoke(app, ["drain", "--json"]).output)["pending"]
    tenant = next(p["id"] for p in pending if p["text"].startswith("Tenant"))
    assert runner.invoke(app, ["drain", "--dismiss", f"{tenant}=planned"]).exit_code == 0

    assert json.loads(runner.invoke(app, ["status", "--json"]).output)["braindump"]["planned"] == 1
    assert "1 planned rule(s)" in runner.invoke(app, ["status"]).output
    listed = runner.invoke(app, ["drain"]).output
    assert "1 planned rule(s), waiting for their code" in listed and tenant in listed
    assert json.loads(runner.invoke(app, ["drain", "--json"]).output)["planned"][0]["id"] == tenant
    assert braindump.PLANNED_HEADING in runner.invoke(app, ["context", "src/app.py"]).output

    monkeypatch.setenv("SEAMSPEC_ROOT", str(tmp_path))

    async def call(name: str, args: dict):
        async with Client(mcp) as client:
            return json.loads((await client.call_tool(name, args)).content[0].text)

    got = anyio.run(call, "get_constraints", {"files": ["src/app.py"]})
    assert got["planned"]["rules"][0]["id"] == tenant and got["planned"]["note"] == braindump.PLANNED_HEADING
    assert anyio.run(call, "braindump_pending", {})["planned"][0]["id"] == tenant
