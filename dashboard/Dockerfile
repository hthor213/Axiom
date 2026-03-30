FROM python:3.12-slim

# System deps: git (for worktrees), curl (for healthcheck), ssh (for git push)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl openssh-client gnupg \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI (for self-deploy: rebuild + restart after merge)
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Node.js (for Claude Code CLI — the autonomous build agent)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Python deps (cached layer)
COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright for functional verification (spec 029)
RUN pip install --no-cache-dir pytest-playwright \
    && playwright install chromium --with-deps

# Application code
COPY dashboard/ /app/dashboard/

# Library code (harness, runtime, ship, orchestrator, registry, platform_*)
COPY lib/python/ /app/lib/python/

# CLI (needed for hth-platform commands invoked by agents)
COPY cli/ /app/cli/
RUN pip install --no-cache-dir -e /app/cli/

# PYTHONPATH: app root (for 'dashboard.api.app'), lib (for 'harness', 'runtime', 'ship')
ENV PYTHONPATH=/app:/app/lib/python

# GIT_COMMIT baked at build time for deployment tracking
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# Repo mounted at runtime for spec scanning + git worktree operations
ENV REPO_ROOT=/repo
# Git config: safe directory (host-mounted repo) + commit identity
RUN git config --global --add safe.directory /repo \
    && git config --global --add safe.directory '*' \
    && git config --global user.name "hth-dashboard" \
    && git config --global user.email "149098249+hthor213@users.noreply.github.com"

EXPOSE 8014

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8014/health || exit 1

CMD ["uvicorn", "dashboard.api.app:app", "--host", "0.0.0.0", "--port", "8014"]
