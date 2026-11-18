FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    FRONTEND_DIR=/app/frontend

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/app backend/app
COPY frontend frontend

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 scout && mkdir -p /data && chown scout /data
USER scout

# Claude Code CLI for the Terminal agent provider; it signs in with CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`)
ARG CLAUDE_CODE_VERSION=stable
ADD --chown=scout https://claude.ai/install.sh /tmp/claude-install.sh
RUN bash /tmp/claude-install.sh "$CLAUDE_CODE_VERSION" && rm /tmp/claude-install.sh && /home/scout/.local/bin/claude --version
# Codex CLI for the Codex agent provider: OpenAI's static Linux build. It signs in on the ChatGPT plan with
# `codex login --device-auth` (see Agents → Settings); CODEX_HOME is on the data volume because token refreshes rewrite it
ARG CODEX_VERSION=0.162.1
RUN curl -fsSL "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-x86_64-unknown-linux-musl.tar.gz" \
      | tar -xz -C /home/scout/.local/bin && mv /home/scout/.local/bin/codex-x86_64-unknown-linux-musl /home/scout/.local/bin/codex \
    && /home/scout/.local/bin/codex --version
# its code-mode host, next to it: Codex calls MCP tools (AXoR's, in native tool-call mode: codex_bridge.py) from code mode,
# a bare V8 runtime with only the tool bindings; without the host every tool call fails with "tool host failed to start"
RUN curl -fsSL "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-code-mode-host-x86_64-unknown-linux-musl.tar.gz" \
      | tar -xz -C /home/scout/.local/bin \
    && mv /home/scout/.local/bin/codex-code-mode-host-x86_64-unknown-linux-musl /home/scout/.local/bin/codex-code-mode-host
ENV CODEX_HOME=/data/codex
# GitHub Copilot CLI for the CLI → GitHub (Copilot) provider (copilot_cli.py): GitHub's standalone Linux build (no Node
# needed). Each run gets the saved GitHub token as COPILOT_GITHUB_TOKEN and a throwaway COPILOT_HOME; --no-auto-update keeps this version
ARG COPILOT_VERSION=1.0.109
RUN curl -fsSL "https://github.com/github/copilot-cli/releases/download/v${COPILOT_VERSION}/copilot-linux-x64.tar.gz" \
      | tar -xz -C /home/scout/.local/bin && chmod +x /home/scout/.local/bin/copilot \
    && HOME=/tmp /home/scout/.local/bin/copilot --version
ENV PATH=/home/scout/.local/bin:$PATH
VOLUME ["/data"]
EXPOSE 8000

# One image, two roles: when PID 1 is the egress proxy (k8s/base/57-egress.yaml, the e2e staging instance) the check is the proxy's own;
# else the web app's. k8s ignores this line (the pods have their own probes); plain Docker runs use it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD if grep -qa egress_proxy /proc/1/cmdline; then exec python /app/backend/app/egress_proxy.py --health; \
      else exec python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"; fi

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
