import json

from exportcli import main


def write_records(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return str(path)


def test_exports_every_record_to_a_file(tmp_path) -> None:
    source = write_records(
        tmp_path / "in.jsonl",
        [
            {"id": 1, "name": "Ada", "email": "ada@example.com", "amount_cents": 1250},
            {"id": 2, "name": "Grace", "email": "grace@example.com", "amount_cents": 300},
        ],
    )
    out = tmp_path / "out.csv"
    main([source, "-o", str(out)])
    lines = out.read_text().splitlines()
    assert len(lines) == 3 and "Ada" in lines[1] and "Grace" in lines[2]


def test_blank_lines_are_ignored(tmp_path) -> None:
    source = tmp_path / "in.jsonl"
    source.write_text('\n{"id": 1, "name": "Ada", "email": "a@example.com", "amount_cents": 5}\n\n')
    out = tmp_path / "out.csv"
    main([str(source), "-o", str(out)])
    assert len(out.read_text().splitlines()) == 2


def test_names_with_commas_are_quoted(tmp_path) -> None:
    source = write_records(
        tmp_path / "in.jsonl", [{"id": 9, "name": "Lovelace, Ada", "email": "a@example.com", "amount_cents": 1}]
    )
    out = tmp_path / "out.csv"
    main([source, "-o", str(out)])
    assert '"Lovelace, Ada"' in out.read_text()
