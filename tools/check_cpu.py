"""The behavior oracle, not an expected-output generator."""
import json
from pathlib import Path
import sys

out = Path(sys.argv[1])
busy = json.loads((out / "cpu-before.txt").read_text())["cpu_percent_one_core"]
fixed = json.loads((out / "cpu-after.txt").read_text())["cpu_percent_one_core"]
if not (busy >= 20 and fixed <= 5 and fixed < busy / 4):
    raise SystemExit(f"FAIL: insufficient CPU contrast: busy={busy}, fixed={fixed}")
print("PASS: busy >= 20% of one core; fixed <= 5%; fixed < busy/4")
