# Linux support evidence: two small, reproducible failures

**Synthetic lab scenarios, not production incidents.** This packet demonstrates
a support workflow: reproduce a symptom, collect Linux evidence, distinguish a
root cause from a guess, apply a narrow fix, and verify the actual outcome.
It does not run GitLab or claim a defect in GitLab, employment, or LFCE/RHCE
certification equivalence. Implementation and documentation were AI-assisted;
the author should rehearse the walkthrough before presenting it as a skill sample.

| Scenario | Tools / evidence | Recovery checked |
|---|---|---|
| Idle daemon burns a CPU core | `ps`, bounded `strace -p`, `/proc/PID/stat`, source inspection | Replace busy loop with a blocking wait; low CPU, still alive, clean shutdown |
| Service starts on an occupied port | `ss -ltnp`, bind-error log, config, loopback TCP test | Correct the app's port; verify its exact response and preserve the existing listener |

Start with [DIAGNOSIS.md](DIAGNOSIS.md). Each case includes the symptom, exact
commands, quoted real output, explanation, fix, verification and an escalation note.

## Reproduce without changing the host

Requirements: a working Docker Engine/Desktop and Bash. No host Python, Linux
packages, `sudo`, Compose, systemd, API keys or cloud resources are needed.
Run these commands **from this packet's directory**:

```sh
# Keep the shipped run-1/run-2 evidence intact; use fresh labels for your replay.
bash reproduce.sh run-local-1
bash reproduce.sh run-local-2

docker run --rm --pull=never --network=none --read-only \
  --entrypoint python3 \
  --mount "type=bind,src=$(pwd)/observed,dst=/observed,readonly" \
  linux-support-evidence:1 /lab/tools/compare.py \
  /observed/run-local-1 /observed/run-local-2
```

`reproduce.sh` builds the image, then uses a **new `docker run --rm` for each
scenario**. It never reuses a running container. It writes raw stdout/stderr,
command transcripts with exit statuses, service logs, measurements, image config
ID and executed-source hashes under `observed/<label>/`. Expected fault exits are
asserted, not silently ignored. A missing failure, failed recovery, unexpected
tracer error or total runtime of 180 seconds or more returns nonzero.

Existing evidence is never overwritten by default. Choose a new label to rerun.
For an explicit repair only, `--archive-existing` moves the old run intact to
`observed/trial-previous-<label>/` before replay; it refuses if that archive already
exists. Development attempts are excluded by `.gitignore`, not destroyed.
Do not run two copies concurrently: they share the local image tag.

### Docker commands underneath

The build command is:

```sh
docker build --provenance=false --progress=plain -t linux-support-evidence:1 .
```

The runner also passes `--iidfile observed/<label>/image-config-id.txt`. This is
BuildKit's **config digest**, not a runnable manifest digest on every Docker
image store. Runtime uses the freshly built local tag with `--pull=never`.

For a direct replay to the terminal without keeping files, these are equivalent
scenario commands (temporary `/evidence` replaces the runner's evidence bind mount):

```sh
docker run --rm --pull=never --network=none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --tmpfs /evidence:rw,nosuid,nodev,size=8m \
  --pids-limit=64 --memory=128m --cpus=1 --cap-add=SYS_PTRACE \
  linux-support-evidence:1 cpu

docker run --rm --pull=never --network=none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --tmpfs /evidence:rw,nosuid,nodev,size=8m \
  --pids-limit=64 --memory=128m --cpus=1 \
  linux-support-evidence:1 port
```

The actual runner substitutes
`--mount "type=bind,src=$out/$scenario,dst=/evidence"` for the `/evidence` tmpfs.
Only that new scenario-output directory is writable on the host. The image
entrypoint limits each scenario to 40 seconds, with a 3-second kill grace period.
No ports are published. TCP probes stay on the container's own loopback interface.

## Pins and environment

- Base: `debian:bookworm-20250224-slim`, pinned to the multi-platform image digest
  `sha256:12c396bd585df7ec21d5679bb6a83d4878bc4415ce926c9e5ea6426d23c60bdc`.
- Dependencies: the signed Debian snapshot dated `20250301T000000Z`, suite
  `bookworm`, component `main`. Only repository-expiry checking is disabled;
  signature verification is not disabled. No pip packages are installed.
- Observed packages: `procps 2:4.0.2-3`, `iproute2 6.1.0-3`, `strace 6.1-0.1`,
  `coreutils 9.1-1`, `python3 3.11.2-1+b1`.
- Verified here: Docker server **28.5.1**, native **Linux arm64/aarch64**, kernel
  `6.10.14-linuxkit` on Docker Desktop. No amd64 or other-kernel verification claim.

Network is needed for the initial registry/package downloads at **build time**.
After building, the scenario and verification containers use `--network=none`;
they need no outbound network. Re-running the build may still consult the registry
even when layers are cached. The image digest and repository snapshot pin inputs,
not the host kernel, hardware, scheduler or byte-for-byte OCI rebuild metadata.
This intentionally old, frozen image is a teaching fixture, **not a deployment
base or a claim of current security patching**.

## Actual verification receipt

The final two complete runs were captured on 17 October 2026:

| Evidence | Run 1 | Run 2 |
|---|---:|---:|
| Full `reproduce.sh` runtime, including cached build | 7 s | 6 s |
| Busy daemon, two-second CPU sample (% of one core) | 99.22 | 98.91 |
| Fixed daemon, same sampling method | 0.00 | 0.00 |
| `strace` attached / syscall lines in one second | yes / 0 | yes / 0 |
| Port failure and exact-response recovery checks | pass | pass |

- [43 paired scenario artifacts compared successfully](observed/comparison.txt),
  including both transcripts. Faults, fixes, service identities, exit statuses,
  versions and source hashes match; no unexpected diagnostic was filtered out.
- [Clean `--no-cache` build passed](observed/clean-build-final.log). This bypassed
  Docker layer cache, not necessarily registry/proxy caches. Benign debconf
  frontend fallback messages appear in the raw log; installation completed.
- [Eight focused tests passed](observed/tests-final.txt): CPU oracle positive and
  negative controls, exact TCP service identity, and normalization that retains
  meaningful differences such as wrong ports, errno, versions and exit codes.

Run the same tests entirely in Docker:

```sh
docker run --rm --pull=never --network=none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m --entrypoint python3 \
  linux-support-evidence:1 -m unittest discover -s /lab/tools -p 'test_*.py' -v
```

The tests are local self-verification, not an independent audit. Clean build command:
`docker build --no-cache --provenance=false --progress=plain -t linux-support-evidence:1 .`.
To check the supplied receipts rather than new ones, pass `/observed/run-1` and
`/observed/run-2` to `compare.py` using the read-only mount above.

### What “deterministic” means here

Raw files are **never normalized in place**. `tools/compare.py` compares their
contents in memory after these explicit transformations:

1. Replace process IDs and parent IDs, including PID-bearing command arguments,
   `/proc` paths and `ss`/`strace` metadata.
2. Replace measured CPU percentages, user/system tick counts and sample durations.
   First recheck counter arithmetic and the actual contrast: busy ≥20% of one
   core, fixed ≤5%, and fixed less than one-quarter of busy. A flat or still-busy
   measurement fails rather than being hidden by normalization.
3. Sort `ps`/`ss` data rows and ignore table alignment/trailing whitespace. Socket
   enumeration order and CPU-based sort order are not stable contracts. Process
   state, commands, ports, queues, descriptors and service names remain checked.

Build progress/cache hits and wall-clock timestamps are provenance, not deterministic
scenario output; `build.log` and `timing.txt` are not equality-compared. Each run's
elapsed-time bound is checked. CPU thresholds are broad behavior checks, not a
benchmark: very overloaded/throttled hosts can fail them. Inspect the measurements
before deciding to rerun; do not weaken the checks just to get green output.

## `strace` permission limits and safe interpretation

Only the CPU scenario adds `SYS_PTRACE`. No `--privileged`, host PID namespace,
host security setting change or `seccomp=unconfined` is used. Both recorded attaches
succeeded. A separate [without-capability replay](observed/ptrace-without-cap.txt)
also attached successfully on this host; that does **not** establish that other
Docker/rootless/kernel policies permit it.

If a host still denies attachment, the script retains the actual denial, records
`"strace":"denied"`, and uses `ps` plus `/proc/PID/stat` deltas. It does not claim
a successful trace or loosen host policy. That denied-attach branch was not
exercised on this host. Unexpected errors still fail. An empty trace alone is
not evidence of a CPU loop: check attachment, liveness, CPU growth and source
together, as the walkthrough does.

## Files, publication boundary and remaining limits

- `Dockerfile`, `.dockerignore`, `.gitignore`, `reproduce.sh`: isolated setup/run.
- `scenarios/`: two small fixtures and their command-by-command diagnostic scripts.
- `tools/`: CPU sampler/oracle, exact TCP probe, comparator and focused tests.
- `observed/run-1/`, `observed/run-2/`: accepted raw receipts; keep empty files,
  especially the **successfully attached but quiet** `cpu/strace.txt`.
- `observed/clean-build-final.log`, `tests-final.txt`, `comparison.txt`,
  `ptrace-without-cap.txt`: supporting verification.
- `BUILD_RECORD.md` and gitignored development attempts: local history, not part
  of the suggested public file set. No private dossier or customer data is needed.

These are tiny fixtures, not HTTP/TLS services, service-manager exercises, real
customer incidents, load tests or permission/ownership examples. The CPU daemon
only demonstrates idle behavior and shutdown, not useful job processing. The
port exercise assumes the documented app endpoint is **8081**; in production,
first confirm the contract rather than arbitrarily moving a port. Tracing can
pause a target and expose sensitive arguments in real systems; authorization,
redaction and incident-safe timing would be required there.

Nothing has been posted, pushed or deployed by this packet. Next: rehearse the two
cases, explain why each piece of evidence supports (or does not support) the
conclusion, then make the separate author-owned publication/licensing decision.
