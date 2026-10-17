"""Sample /proc/PID/stat CPU ticks without strace overhead (one-core scale)."""
import json
import os
from pathlib import Path
import sys
import time


pid = int(sys.argv[1])
seconds = float(sys.argv[2])
source = Path(f"/proc/{pid}/stat")


def ticks():
    # The command name in parentheses can contain spaces; don't split it as fields.
    fields = source.read_text().rsplit(")", 1)[1].split()
    return int(fields[11]), int(fields[12])  # Original fields 14 (utime), 15 (stime).


hz = os.sysconf("SC_CLK_TCK")
before = ticks()
start = time.monotonic()
time.sleep(seconds)
after = ticks()
elapsed = time.monotonic() - start
delta = sum(after) - sum(before)
print(json.dumps({
    "pid": pid, "source": str(source), "clock_ticks_per_second": hz,
    "utime_before": before[0], "stime_before": before[1],
    "utime_after": after[0], "stime_after": after[1],
    "delta_ticks": delta, "sample_seconds": round(elapsed, 6),
    "cpu_percent_one_core": round(delta / hz / elapsed * 100, 2),
}, indent=2, sort_keys=True))
