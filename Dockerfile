# Production-oriented Linux image for the loom-server composition root.
FROM rust:1.97-bookworm AS builder

WORKDIR /src
COPY Cargo.toml Cargo.lock rust-toolchain.toml rustfmt.toml ./
COPY apps ./apps
COPY capabilities ./capabilities
COPY crates ./crates
COPY tests ./tests
COPY tools ./tools
COPY docs ./docs

RUN cargo build --release -p loom-server

FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 999 loom \
    && useradd --system --uid 999 --gid 999 --create-home --home-dir /var/lib/loom --shell /usr/sbin/nologin loom \
    && install --directory --owner=loom --group=loom /var/lib/loom/blobs

COPY --from=builder /src/target/release/loom-server /usr/local/bin/loom-server
COPY docker/loom-entrypoint.sh /usr/local/bin/loom-entrypoint.sh

RUN chmod 0755 /usr/local/bin/loom-entrypoint.sh

ENV LOOM_DATA_DIR=/var/lib/loom \
    LOOM_BIND_ADDR=0.0.0.0:8080

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/loom-entrypoint.sh"]
