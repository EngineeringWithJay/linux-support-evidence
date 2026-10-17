# Sourced by run.sh inside the disposable container.
start_child daemon-before python3 /lab/scenarios/idle_daemon.py busy
busy=$child
wait_ready "$busy" daemon-before
sleep 0.2
expect 0 ps-before ps -eo pid,ppid,pcpu,comm,args --sort=-pcpu
expect 0 cpu-before python3 /lab/tools/cpu_sample.py "$busy" 2

# A quiet trace is meaningful only if attachment actually succeeded.
trace_status=0
capture strace-attach timeout --signal=INT --kill-after=2s 1s \
    strace -p "$busy" -o "$OUT/strace.txt" || trace_status=$?
if [[ $trace_status == 124 ]] && grep -q 'attached' "$OUT/strace-attach.txt"; then
    trace_result=attached
elif [[ $trace_status == 1 ]] && grep -Eq 'Operation not permitted|Permission denied' "$OUT/strace-attach.txt"; then
    trace_result=denied
    printf 'LIMIT: ptrace denied; using measured /proc CPU ticks, not claiming a trace.\n'
else
    printf 'FAIL: unexpected strace status=%s\n' "$trace_status" >&2
    exit 1
fi
expect 0 trace-lines wc -l "$OUT/strace.txt"
expect 0 survived-trace kill -0 "$busy"
expect 0 source nl -ba /lab/scenarios/idle_daemon.py
expect 0 stop-busy kill -TERM "$busy"
expect 0 reap-busy wait "$busy"
if kill -0 "$busy" 2>/dev/null; then
    printf 'FAIL: busy daemon still exists after wait\n' >&2
    exit 1
fi
printf 'VERIFIED: busy daemon exited and was reaped\n'
expect 0 daemon-before-log cat "$OUT/daemon-before.txt"

start_child daemon-after python3 /lab/scenarios/idle_daemon.py fixed
fixed=$child
wait_ready "$fixed" daemon-after
expect 0 cpu-after python3 /lab/tools/cpu_sample.py "$fixed" 2
expect 0 ps-after ps -p "$fixed" -o pid,ppid,stat,pcpu,comm,args
expect 0 cpu-check python3 /lab/tools/check_cpu.py "$OUT"
expect 0 fixed-alive kill -0 "$fixed"
expect 0 stop-fixed kill -TERM "$fixed"
expect 0 reap-fixed wait "$fixed"
expect 0 daemon-after-log cat "$OUT/daemon-after.txt"
printf '{"scenario":"cpu","cpu_contrast":"pass","busy_reaped":true,"fixed_alive_before_stop":true,"fixed_shutdown":"pass","strace":"%s"}\n' \
    "$trace_result" > "$OUT/result.json"
