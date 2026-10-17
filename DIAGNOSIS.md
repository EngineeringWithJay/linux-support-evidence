# Support walkthrough: symptom → evidence → cause → fix → verification

**Scope:** two deliberately broken synthetic Linux fixtures. No production
incident, customer impact, GitLab defect or certification is claimed. Quoted
outputs below are literal excerpts from `observed/run-1/`, unless marked run 2.
PIDs and measurements are observations, not values to hard-code in a new run.

The automated reproduction is `bash reproduce.sh <new-run-label>` from this
packet directory. It launches each scenario in a **fresh container**, runs every
command, asserts expected exits and keeps the evidence. `transcript.txt` is the
complete command/exit-status record; the other files contain individual outputs.
The command blocks explain that sequence, not a separate copy-paste harness:
the runner supplies readiness checks, output-file redirection, expected-error
handling and cleanup. Use `reproduce.sh` for a complete runnable session.

## 1. Idle daemon consumes a core

### Symptom and expected behavior

The daemon is ready but has no work. It should block while idle and still stop
cleanly on SIGTERM. Instead, `ps` identifies `idle_daemon.py busy` as the CPU-heavy
process. This is a **process-level resource symptom**, not proof of whole-host
saturation or user-visible latency.

### Reproduce and triage: exact commands

The following commands run **inside the lab container**, not on the host. `$busy`
is the PID captured when starting this fixture; in the automated run, readiness
is bounded and the parent creates the log before starting the child.

```sh
python3 /lab/scenarios/idle_daemon.py busy > /evidence/daemon-before.txt 2>&1 &
busy=$!
# Wait for READY before sampling; the scripted runner does this automatically.
ps -eo pid,ppid,pcpu,comm,args --sort=-pcpu
python3 /lab/tools/cpu_sample.py "$busy" 2
timeout --signal=INT --kill-after=2s 1s \
  strace -p "$busy" -o /evidence/strace.txt
wc -l /evidence/strace.txt
kill -0 "$busy"
nl -ba /lab/scenarios/idle_daemon.py
```

**Why these commands?** `ps` finds the process without knowing its PID in advance;
the launch PID then confirms its identity. The CPU sampler reads user/system tick
counters from `/proc/PID/stat` fields 14 and 15 twice, two seconds apart. It uses
`SC_CLK_TCK`, not an assumed tick rate:

```text
CPU percent of one core = 100 × (delta user ticks + delta system ticks)
                              / clock ticks per second / elapsed seconds
```

This is a small transparent `/proc` reader, not a profiler. Sampling happens
before tracing, so tracer overhead is not included in that CPU measurement.
`strace` is unfiltered and attaches for only one second. `timeout` exit **124**
means the observation window ended; it is expected here, not a service failure.
The script separately requires evidence that attachment succeeded and checks
that the target is still alive after detachment.

### Observed evidence

[`cpu/ps-before.txt`](observed/run-1/cpu/ps-before.txt):

```text
   16     7 96.8 python3         python3 /lab/scenarios/idle_daemon.py busy
```

[`cpu/cpu-before.txt`](observed/run-1/cpu/cpu-before.txt), selected exact lines:

```text
  "clock_ticks_per_second": 100,
  "cpu_percent_one_core": 99.22,
  "delta_ticks": 199,
  "sample_seconds": 2.005709,
  "stime_after": 0,
  "stime_before": 0,
  "utime_after": 231,
  "utime_before": 32
```

[`cpu/strace-attach.txt`](observed/run-1/cpu/strace-attach.txt) and
[`cpu/trace-lines.txt`](observed/run-1/cpu/trace-lines.txt), respectively:

```text
strace: Process 16 attached
strace: Process 16 detached
```

```text
0 /evidence/strace.txt
```

The syscall trace file is really empty. That is **not** a missing capture: the
separate stderr record establishes attachment and detachment, and `kill -0`
succeeded. The busy process accumulated user CPU time while the short trace
showed no syscalls. A sleeping process can also have a quiet trace, so silence
alone would be inconclusive. Here the CPU counters and inspected source identify
the deliberately injected user-space spin.

Run 2 independently measured **98.91%** over **2.00182 seconds**, also with zero
traced syscall lines. Its early `ps` snapshot showed **103%**: `ps %CPU` is based on
process lifetime, and short-lived-process tick/elapsed accounting can yield such
values. Do not turn either `ps` value into a precise benchmark; use the measured
two-second counter delta for this comparison.

### Root cause and narrow fix

The ready daemon executes `while True: pass` in `busy` mode. There is no work and
no blocking operation. The `fixed` branch uses `signal.pause()` to let the kernel
sleep the process until a signal arrives. This is suitable for **this signal-only
idle fixture**, not a universal job-queue implementation. A real queue worker
would normally block on its actual queue/event source instead.

Stop the identified process gracefully, reap it, and start the fixed branch:

```sh
kill -TERM "$busy"
wait "$busy"
python3 /lab/scenarios/idle_daemon.py fixed > /evidence/daemon-after.txt 2>&1 &
fixed=$!
# After READY:
python3 /lab/tools/cpu_sample.py "$fixed" 2
ps -p "$fixed" -o pid,ppid,stat,pcpu,comm,args
python3 /lab/tools/check_cpu.py /evidence
kill -0 "$fixed"
kill -TERM "$fixed"
wait "$fixed"
```

The runner saves the samples as `cpu-before.txt` and `cpu-after.txt` for the
oracle. It asserts the old PID is gone after `wait`; killing without replacing
the daemon is not counted as recovery. It also checks the replacement is alive
before intentionally stopping it and that SIGTERM exits successfully.

### Verification and support handoff

[`cpu/cpu-after.txt`](observed/run-1/cpu/cpu-after.txt):

```text
  "cpu_percent_one_core": 0.0,
  "delta_ticks": 0,
```

[`cpu/ps-after.txt`](observed/run-1/cpu/ps-after.txt):

```text
   40     7 S     0.0 python3         python3 /lab/scenarios/idle_daemon.py fixed
```

[`cpu/cpu-check.txt`](observed/run-1/cpu/cpu-check.txt):

```text
PASS: busy >= 20% of one core; fixed <= 5%; fixed < busy/4
```

[`cpu/daemon-after.txt`](observed/run-1/cpu/daemon-after.txt):

```text
READY mode=fixed
STOPPED signal=SIGTERM
```

**Support/bug-report summary:** “Idle loop repeatedly executes without blocking;
ready daemon consumes approximately one core with no pending work. Reproduced in
both pinned synthetic runs. Replace the spin with the appropriate blocking wait;
two-second idle CPU drops to zero and graceful shutdown remains functional.”
Attach the process snapshot, both CPU samples, successful-attach stderr, empty
trace, source hash and shutdown log. No production throughput or latency claim.
If ptrace is denied, say so explicitly and attach the `/proc` evidence instead;
do not call a denied trace a quiet trace.

## 2. App startup fails and its endpoint refuses connections

### Symptom and expected behavior

The lab's endpoint contract is explicit: `incumbent` owns loopback **8080** and
`app` should serve loopback **8081**. The app's synthetic config incorrectly says
`PORT=8080`. Its startup exits and the expected endpoint refuses connections.

This is not proof of DNS, firewall, TLS, remote-network or HTTP trouble: the
client connects directly to an IP address inside the same network namespace.

### Reproduce and triage: exact commands

Inside a **new** lab container, the runner starts the incumbent, waits for READY,
and creates the deliberately incorrect config:

```sh
python3 /lab/scenarios/tcp_service.py incumbent 8080 > /evidence/incumbent.txt 2>&1 &
incumbent=$!
# After READY:
printf 'PORT=8080\n' > /tmp/app.env
cat /tmp/app.env
source /tmp/app.env
python3 /lab/scenarios/tcp_service.py app "$PORT"
ss -ltnp '( sport = :8080 or sport = :8081 )'
python3 /lab/tools/probe.py 8081 app
python3 /lab/tools/probe.py 8080 incumbent
```

`ss -ltnp`: listening sockets, TCP, numeric addresses/ports, owning processes.
The two app-start/probe failures are **expected and explicitly asserted** by the
runner (exit 78 for this fixture's configuration failure; exit 2 for the probe's
connection error). Those are fixture exit codes, not Linux errno numbers.

### Observed evidence

[`port/config-before.txt`](observed/run-1/port/config-before.txt):

```text
PORT=8080
```

[`port/app-failed.txt`](observed/run-1/port/app-failed.txt):

```text
ERROR service=app bind=127.0.0.1:8080 errno=98 EADDRINUSE
```

[`port/ss-before.txt`](observed/run-1/port/ss-before.txt):

```text
LISTEN 0      8          127.0.0.1:8080      0.0.0.0:*    users:(("python3",pid=16,fd=3))
```

[`port/connect-before.txt`](observed/run-1/port/connect-before.txt):

```text
CONNECT 127.0.0.1:8081 failed: errno=111 ECONNREFUSED
```

[`port/incumbent-before.txt`](observed/run-1/port/incumbent-before.txt):

```text
CONNECT 127.0.0.1:8080 response=service=incumbent status=ok
```

### Root cause and narrow fix

The app tried to bind an address already owned by the incumbent. `ss` connects the
occupied socket to a process, and the exact TCP response confirms its service
identity. The startup log supplies `EADDRINUSE`; no listener exists on the app's
intended 8081, explaining this lab's `ECONNREFUSED`. A refusal by itself would not
identify the cause on an arbitrary production network.

Correct **the app's configuration**, not the healthy incumbent. Do not kill a
listener merely because it owns the port you wanted, and do not widen the bind
address or change host firewall rules:

```sh
printf 'PORT=8081\n' > /tmp/app.env
cat /tmp/app.env
source /tmp/app.env
python3 /lab/scenarios/tcp_service.py app "$PORT" > /evidence/app-after.txt 2>&1 &
app=$!
# After READY:
cat /evidence/app-after.txt
ss -ltnp '( sport = :8080 or sport = :8081 )'
python3 /lab/tools/probe.py 8081 app
python3 /lab/tools/probe.py 8080 incumbent
kill -0 "$app"
kill -0 "$incumbent"
```

The probe is a standard-library TCP client with a two-second socket timeout and
small response limit. It requires the **exact service response**, not just an
open port. The fixture logs are collected directly; there is no systemd journal
inside this small container. The runner stops/reaps both fixtures on exit.

### Verification and support handoff

[`port/app-after-log.txt`](observed/run-1/port/app-after-log.txt):

```text
READY service=app listen=127.0.0.1:8081
```

[`port/ss-after.txt`](observed/run-1/port/ss-after.txt), app listener:

```text
LISTEN 0      8          127.0.0.1:8081      0.0.0.0:*    users:(("python3",pid=32,fd=3))
```

[`port/connect-after.txt`](observed/run-1/port/connect-after.txt) and
[`port/incumbent-after.txt`](observed/run-1/port/incumbent-after.txt), respectively:

```text
CONNECT 127.0.0.1:8081 response=service=app status=ok
```

```text
CONNECT 127.0.0.1:8080 response=service=incumbent status=ok
```

Both recorded runs produced these same failure/recovery lines and kept the
incumbent available. Two listeners plus correct application responses establish
the lab's recovery more strongly than “the process started” alone.

**Support/configuration-report summary:** “App configuration duplicates the
incumbent's port 8080 instead of its documented 8081. Startup exits 78 with errno
98; expected endpoint refuses connections with errno 111. Correcting `PORT` and
restarting only the app restores its exact TCP response while preserving the
incumbent.” Attach before/after config, bind log, `ss` snapshots and both probes.
If this happened in a generated deployment, investigate the source of the bad
config and add preflight validation; this fixture does not establish an upstream
software bug or justify a public bug report about a real product.

## Practice explaining the evidence

1. Why can a CPU-heavy process have an empty `strace`? Why is that not enough
   evidence on its own? What would a denied attach look like instead?
2. Why is `ps %CPU` different from a two-second `/proc` delta? Why does a
   replacement process need a liveness check as well as lower CPU?
3. What is the difference between `EADDRINUSE` at startup and `ECONNREFUSED` at
   connect time? Which evidence connects the two here?
4. Why verify the app's response identity and the incumbent's continued health?
   What would need approval or more evidence before doing these steps in production?
