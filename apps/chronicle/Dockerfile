# Stage 1: build the long-lived Rust Chronicle server (C1-T2).
# The web UI is embedded into the binary at compile time, so both the
# server sources and the zero-build web directory are build inputs.
FROM rust:1.97.1-slim-bookworm AS chronicle-server-builder

WORKDIR /opt/build

COPY apps/chronicle/server/Cargo.toml apps/chronicle/server/Cargo.toml
COPY apps/chronicle/server/src apps/chronicle/server/src
COPY apps/chronicle/web apps/chronicle/web

RUN cd apps/chronicle/server && cargo build --release

# Stage 2: Python runtime for the C0 read-model sidecar plus the Rust binary.
# Chronicle remains application-owned product persistence behind
# CHRONICLE_DATABASE_URL (Architecture Amendment 0006).
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/loom

COPY apps/chronicle/persistence/requirements.txt /tmp/chronicle-persistence-requirements.txt
COPY apps/chronicle/read_api/requirements.txt /tmp/chronicle-read-api-requirements.txt

RUN python3 -m pip install --no-cache-dir \
      -r /tmp/chronicle-persistence-requirements.txt \
      -r /tmp/chronicle-read-api-requirements.txt \
    && groupadd --system --gid 10001 chronicle \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin chronicle

COPY --from=chronicle-server-builder \
  /opt/build/apps/chronicle/server/target/release/chronicle-server \
  /usr/local/bin/chronicle-server

COPY --chown=chronicle:chronicle apps/chronicle ./apps/chronicle

USER chronicle

EXPOSE 8080

CMD ["python3", "apps/chronicle/read_api/server.py", "--host", "0.0.0.0", "--port", "8080"]
