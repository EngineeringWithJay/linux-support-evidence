#!/bin/bash
set -euo pipefail
if [[ $# != 1 || ( $1 != cpu && $1 != port ) ]]; then
    printf 'Usage: image cpu|port\n' >&2
    exit 2
fi
OUT=/evidence
children=()
cleanup() {
    for pid in "${children[@]}"; do
        kill -TERM "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

command_line() { printf '+ '; printf '%q ' "$@"; printf '\n'; }
capture() {
    local name=$1 status=0
    shift
    command_line "$@"
    "$@" > "$OUT/$name.txt" 2>&1 || status=$?
    cat "$OUT/$name.txt"
    printf 'exit_status=%s\n' "$status"
    return "$status"
}
expect() {
    local expected=$1 status=0
    shift
    capture "$@" || status=$?
    if [[ $status != "$expected" ]]; then
        printf 'FAIL: expected exit %s, got %s\n' "$expected" "$status" >&2
        exit 1
    fi
}
start_child() {
    local name=$1
    shift
    command_line "$@"
    # Create the log in the parent, before the readiness reader can see it.
    # Redirection in the background child alone races with wait_ready's grep.
    : > "$OUT/$name.txt"
    "$@" > "$OUT/$name.txt" 2>&1 &
    child=$!
    children+=("$child")
    printf 'started_pid=%s log=%s.txt\n' "$child" "$name"
}
wait_ready() {
    local pid=$1 log=$2
    for (( attempt=0; attempt<50; attempt++ )); do
        if grep -q '^READY ' "$OUT/$log.txt"; then return; fi
        if ! kill -0 "$pid" 2>/dev/null; then
            cat "$OUT/$log.txt" >&2
            printf 'FAIL: child exited before readiness\n' >&2
            exit 1
        fi
        sleep 0.1
    done
    printf 'FAIL: readiness timeout\n' >&2
    exit 1
}

printf 'Synthetic Linux support lab: scenario=%s\n' "$1"
expect 0 environment bash -c 'uname -srm; id; dpkg-query -W procps iproute2 strace coreutils python3'
expect 0 source-manifest cat /lab/source.sha256
expect 0 network ip -brief address
source "/lab/scenarios/$1.sh"
printf 'PASS scenario=%s\n' "$1"
