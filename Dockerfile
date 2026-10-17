FROM debian:bookworm-20250224-slim@sha256:12c396bd585df7ec21d5679bb6a83d4878bc4415ce926c9e5ea6426d23c60bdc AS base

FROM base AS lab
ENV LANG=C LC_ALL=C TZ=UTC PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# A dated, signed repository makes the dependency set independent of today's mirror.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20250301T000000Z bookworm main' > /etc/apt/sources.list \
    && apt-get -o Acquire::Retries=2 update \
    && apt-get install -y --no-install-recommends procps iproute2 strace coreutils python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /lab
COPY scenarios/ /lab/scenarios/
COPY tools/ /lab/tools/
RUN sha256sum /lab/scenarios/* /lab/tools/*.py > /lab/source.sha256
ENTRYPOINT ["/usr/bin/timeout", "--signal=TERM", "--kill-after=3s", "40s", "/bin/bash", "/lab/scenarios/run.sh"]
