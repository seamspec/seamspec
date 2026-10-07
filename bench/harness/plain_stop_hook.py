"""Condition D (SPEC §4.4): plain tests plus a Claude Code Stop hook that runs them. No SeamSpec.

Deliberately about as small as an expert would write it: run tests/rules, block the stop with the
output if they fail, give up after 3 blocks in a row so the agent can't loop forever.
"""

import json
import subprocess
import sys
from pathlib import Path

event = json.load(sys.stdin)
root = Path(event.get("cwd") or ".")
cmd = (
    [str(root / ".venv/bin/python"), "-m", "pytest", "-q", "tests/rules"]
    if sys.argv[1] == "pytest"
    else ["npx", "vitest", "run", "tests/rules"]
)
state_file = root / ".git" / "bench-stop-blocks"
blocks = int(state_file.read_text()) if state_file.exists() else 0
result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=240)
if result.returncode == 0 or blocks >= 3:
    state_file.write_text("0")
    sys.exit(0)
state_file.write_text(str(blocks + 1))
output = (result.stdout + result.stderr)[-3000:]
print(json.dumps({"decision": "block", "reason": f"Tests in tests/rules failed. Fix them before finishing:\n{output}"}))
