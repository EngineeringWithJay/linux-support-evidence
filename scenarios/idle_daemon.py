"""Synthetic idle daemon: deliberately spins in busy mode; waits in fixed mode."""
import signal
import sys


def stop(_signal, _frame):
    print("STOPPED signal=SIGTERM", flush=True)
    raise SystemExit(0)


mode = sys.argv[1]
if mode not in {"busy", "fixed"}:
    raise SystemExit("mode must be busy or fixed")
signal.signal(signal.SIGTERM, stop)
print(f"READY mode={mode}", flush=True)
if mode == "busy":
    while True:
        pass  # BUG: an idle daemon burns CPU without doing any work.
else:
    while True:
        signal.pause()  # FIX: block until a signal; SIGTERM still shuts down.
