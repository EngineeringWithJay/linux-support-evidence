"""Compare preserved command artifacts; never rewrite the raw evidence."""
import difflib
import json
from pathlib import Path
import re
import sys


MEASUREMENTS = (
    "cpu_percent_one_core", "delta_ticks", "sample_seconds",
    "utime_before", "utime_after", "stime_before", "stime_after",
)
PS_ROW = re.compile(
    r"^\s*\d+\s+\d+\s+(?:(?P<state>[A-Z][a-zA-Z<+]+|[A-Z])\s+)?"
    r"\d+(?:\.\d+)?\s+(?P<comm>\S+)\s+(?P<args>.+)$"
)


def normalize(text):
    """Only PIDs, CPU time measurements and diagnostic-table presentation vary."""
    for key in MEASUREMENTS:
        text = re.sub(rf'("{key}": )\d+(?:\.\d+)?', rf'\1"<measurement>"', text)
    text = re.sub(r'("pid": )\d+', r'\1"<PID>"', text)
    text = re.sub(r"/proc/\d+/stat", "/proc/<PID>/stat", text)
    text = re.sub(r"\b(pid=|started_pid=)\d+", r"\1<PID>", text)
    text = re.sub(r"(Process )\d+( (?:attached|detached))", r"\1<PID>\2", text)
    text = re.sub(r"((?:strace|ps) -p )\d+", r"\1<PID>", text)
    text = re.sub(r"(cpu_sample\.py )\d+( 2)", r"\1<PID>\2", text)
    text = re.sub(r"(\+ kill -(?:TERM|0) )\d+", r"\1<PID>", text)
    text = re.sub(r"(\+ wait )\d+", r"\1<PID>", text)
    lines = []
    table = []

    def flush():
        lines.extend(sorted(table))
        table.clear()

    for line in text.splitlines():
        match = PS_ROW.match(line)
        if match:
            state = f"{match['state']} " if match['state'] else ""
            table.append(f"<PID> <PPID> {state}<%CPU> {match['comm']} {match['args']}")
        elif line.startswith("LISTEN "):
            table.append(" ".join(line.split()))
        else:
            flush()
            lines.append(line.rstrip())
    flush()
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def validate_run(root):
    """Check real measurements before masking them; absence is not a pass."""
    for scenario in ("cpu", "port"):
        transcript = (root / scenario / "transcript.txt").read_text()
        if f"PASS scenario={scenario}\n" not in transcript:
            raise ValueError(f"{scenario}: missing successful completion")
        for name in ("environment.txt", "network.txt", "source-manifest.txt", "result.json"):
            if not (root / scenario / name).read_text().strip():
                raise ValueError(f"{scenario}: missing/empty {name}")
    cpu = root / "cpu"
    before = json.loads((cpu / "cpu-before.txt").read_text())
    after = json.loads((cpu / "cpu-after.txt").read_text())
    busy, fixed = before["cpu_percent_one_core"], after["cpu_percent_one_core"]
    if not (busy >= 20 and fixed <= 5 and fixed < busy / 4):
        raise ValueError("CPU contrast failed before normalization")
    for sample in (before, after):
        delta = sample["utime_after"] + sample["stime_after"] - sample["utime_before"] - sample["stime_before"]
        percent = delta / sample["clock_ticks_per_second"] / sample["sample_seconds"] * 100
        if sample["delta_ticks"] != delta or abs(sample["cpu_percent_one_core"] - percent) > 0.02:
            raise ValueError("CPU measurement/counter inconsistency")
    result = json.loads((cpu / "result.json").read_text())
    expected_cpu = {
        "scenario": "cpu", "cpu_contrast": "pass", "busy_reaped": True,
        "fixed_alive_before_stop": True, "fixed_shutdown": "pass", "strace": result["strace"],
    }
    if result != expected_cpu or result["strace"] not in {"attached", "denied"}:
        raise ValueError("CPU result mismatch")
    trace = (cpu / "strace-attach.txt").read_text()
    if result["strace"] == "attached" and not re.search(r"Process \d+ attached", trace):
        raise ValueError("claimed ptrace attachment missing")
    if result["strace"] == "denied" and not re.search(r"Operation not permitted|Permission denied", trace):
        raise ValueError("claimed ptrace denial missing")
    port = root / "port"
    expected_text = {
        "app-failed.txt": "ERROR service=app bind=127.0.0.1:8080 errno=98 EADDRINUSE\n",
        "connect-before.txt": "CONNECT 127.0.0.1:8081 failed: errno=111 ECONNREFUSED\n",
        "connect-after.txt": "CONNECT 127.0.0.1:8081 response=service=app status=ok\n",
        "incumbent-after.txt": "CONNECT 127.0.0.1:8080 response=service=incumbent status=ok\n",
        "config-before.txt": "PORT=8080\n", "config-after.txt": "PORT=8081\n",
    }
    for name, expected in expected_text.items():
        if (port / name).read_text() != expected:
            raise ValueError(f"port: {name} does not establish the expected fault/recovery")
    expected_port = {
        "scenario": "port", "bind_failure_exit": 78, "connection_refused_exit": 2,
        "fixed_port": 8081, "app_response": "pass", "incumbent_preserved": True,
    }
    if json.loads((port / "result.json").read_text()) != expected_port:
        raise ValueError("port result mismatch")
    timing = (root / "timing.txt").read_text()
    elapsed = re.search(r"^elapsed_seconds=(\d+)$", timing, re.MULTILINE)
    if not elapsed or int(elapsed[1]) >= 180:
        raise ValueError("full replay missing or exceeded the 180-second target")


def compare(left, right):
    validate_run(left)
    validate_run(right)
    count = 0
    for scenario in ("cpu", "port"):
        names = sorted(p.name for p in (left / scenario).iterdir())
        other = sorted(p.name for p in (right / scenario).iterdir())
        if names != other:
            raise ValueError(f"{scenario}: artifact inventories differ")
        for name in names:
            a = normalize((left / scenario / name).read_text())
            b = normalize((right / scenario / name).read_text())
            if a != b:
                diff = "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), "run-1", "run-2"))
                raise ValueError(f"{scenario}/{name}: unexpected difference\n{diff}")
            count += 1
    if (left / "image-config-id.txt").read_text() != (right / "image-config-id.txt").read_text():
        raise ValueError("different image config digests")
    print(f"PASS: {count} scenario artifacts match after documented normalization")
    print("PASS: CPU counters, fault/recovery outputs, result records and <180s budgets validated in both runs")
    print("PASS: same image config digest and executed-source manifests")
    print("NOT compared for sameness: build.log (cache/progress), timing.txt (wall-clock provenance)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: compare.py /observed/run-1 /observed/run-2")
    try:
        compare(Path(sys.argv[1]), Path(sys.argv[2]))
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(f"FAIL: {error}")
