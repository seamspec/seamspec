# exportcli

A small command-line tool that exports customer records from a JSON Lines file to CSV for the finance import. A nightly cron job runs it.

```
python -m exportcli customers.jsonl -o customers.csv
```

Without `-o` the CSV is written to standard output.

Run the tests with `.venv/bin/python -m pytest` (a virtualenv with pytest is in `.venv`).
