# The sandbox runner (axor/sandbox): where Mining HQ's agents run code (backend/app/sandbox.py). The toolchains of the apps that
# Ridges' database tasks use (Python, Go, TypeScript), git, and the PostgreSQL and ClickHouse clients; PostgreSQL and ClickHouse
# themselves run beside it in the pod. Runs as uid 1000 with no network but AXoR's model proxy, so everything is baked in here.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 GOTOOLCHAIN=local GOFLAGS=-mod=mod

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates curl jq procps postgresql-client golang-go nodejs npm build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip install \
      "psycopg[binary]==3.2.3" "asyncpg==0.30.0" "SQLAlchemy==2.0.36" "clickhouse-connect==0.8.11" \
      "pytest==8.3.4" "hypothesis==6.122.3" "requests==2.32.3" "httpx==0.28.1" "openai==1.58.1" "pydantic==2.10.4"
RUN npm install -g typescript@5.7.2 tsx@4.19.2 && npm cache clean --force

# AEF (D-032 Proposed), the developer environment the execution directive lists and the image lacked (measured 2026-11-13:
# g5-plan/aef/evidence/limits-run3, probes E2, E4, E5, E6): CMake and Ninja, a benchmarking tool, Rust, and a headless browser.
# - Rust: one pinned toolchain under /opt/rust, read-only at run time; a run's own registry and build cache go to /tmp/cargo.
# - Browser: Playwright's Chromium under /opt/pw with its system libraries. A run reaches the web only through the egress proxy,
#   which needs the run's token: pass proxy={"server", "username", "password"} from $HTTPS_PROXY to launch(), and
#   args=["--disable-dev-shm-usage"] (a pod's /dev/shm is 64 MB). .axor/ has no helper for it yet.
RUN apt-get update && apt-get install -y --no-install-recommends cmake ninja-build pkg-config hyperfine time \
    && rm -rf /var/lib/apt/lists/*
ENV RUSTUP_HOME=/opt/rust/rustup PATH=/opt/rust/cargo/bin:$PATH
RUN curl -fsSL https://static.rust-lang.org/rustup/archive/1.27.1/x86_64-unknown-linux-gnu/rustup-init -o /tmp/rustup-init \
    && echo "6aeece6993e902708983b209d04c0d1dbb14ebb405ddb87def578d41f920f56d  /tmp/rustup-init" | sha256sum -c - \
    && chmod +x /tmp/rustup-init && CARGO_HOME=/opt/rust/cargo /tmp/rustup-init -y --no-modify-path --profile minimal --default-toolchain 1.85.0 \
    && rm /tmp/rustup-init && chmod -R a+rX /opt/rust
ENV CARGO_HOME=/tmp/cargo PLAYWRIGHT_BROWSERS_PATH=/opt/pw
RUN pip install "playwright==1.49.1" && playwright install --with-deps chromium && chmod -R a+rX /opt/pw && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 sandbox && mkdir -p /work /repo && chown sandbox:sandbox /work /repo
USER 1000
WORKDIR /work
CMD ["bash"]
