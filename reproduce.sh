#!/bin/bash
# Run from this directory: bash reproduce.sh run-1
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 || ! $1 =~ ^(run|trial)-[a-zA-Z0-9-]+$ || ( $# == 2 && $2 != --archive-existing ) ]]; then
    printf 'Usage: bash reproduce.sh run-1 [--archive-existing]\n' >&2
    exit 2
fi
if [[ ! -f Dockerfile || ! -f scenarios/run.sh ]]; then
    printf 'Run this script from the packet directory.\n' >&2
    exit 2
fi
root=$(pwd -P)
out="$root/observed/$1"
if [[ -e "$out" ]]; then
    archive="$root/observed/trial-previous-$1"
    if [[ ${2:-} != --archive-existing || -e "$archive" || -L "$out" || ! -f "$out/timing.txt" ]]; then
        printf 'Refusing to overwrite evidence: observed/%s\n' "$1" >&2
        exit 2
    fi
    # Explicit recovery only: preserve every byte of the old run, never edit it.
    mv "$out" "$archive"
    printf 'Previous evidence preserved in observed/trial-previous-%s\n' "$1"
fi
mkdir -p "$out/cpu" "$out/port"
start=$(date +%s)
date -u '+started_utc=%Y-%m-%dT%H:%M:%SZ' > "$out/timing.txt"
printf 'Building pinned lab image; log: observed/%s/build.log\n' "$1"
if ! docker build --provenance=false --progress=plain \
    --iidfile "$out/image-config-id.txt" -t linux-support-evidence:1 . \
    > "$out/build.log" 2>&1; then
    cat "$out/build.log" >&2
    exit 1
fi
# BuildKit's --iidfile is a config digest, not a runnable manifest digest on
# Docker Desktop's containerd image store. Use the just-built local version tag.
image=linux-support-evidence:1
for scenario in cpu port; do
    printf 'Running %s in a fresh, network-isolated container...\n' "$scenario"
    caps=()
    if [[ $scenario == cpu ]]; then caps=(--cap-add=SYS_PTRACE); fi
    if ! docker run --rm --pull=never --network=none \
        --read-only --tmpfs /tmp:rw,nosuid,nodev,size=32m \
        --pids-limit=64 --memory=128m --cpus=1 \
        ${caps[@]+"${caps[@]}"} \
        --mount "type=bind,src=$out/$scenario,dst=/evidence" \
        "$image" "$scenario" > "$out/$scenario/transcript.txt" 2>&1; then
        cat "$out/$scenario/transcript.txt" >&2
        printf 'FAILED: raw output retained in observed/%s/%s\n' "$1" "$scenario" >&2
        exit 1
    fi
    cat "$out/$scenario/transcript.txt"
done
elapsed=$(( $(date +%s) - start ))
printf 'elapsed_seconds=%s\n' "$elapsed" >> "$out/timing.txt"
printf 'PASS: both scenarios; elapsed_seconds=%s; evidence=observed/%s\n' "$elapsed" "$1"
if (( elapsed >= 180 )); then
    printf 'Runtime target missed (includes image build); see build.log and timing.txt.\n' >&2
    exit 1
fi
