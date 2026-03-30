# 028: Infrastructure Design — Server Service Architecture

**Status:** draft

## Goal

Define the target infrastructure for a dedicated server: every application service runs in a Docker container, managed by a single docker-compose stack. Stopping Docker disables all project workloads — the machine is instantly available for other use with zero resource overhead from dev services.

## Design (target state)

### Container architecture

All application services run in Docker containers orchestrated by a single `docker-compose.yml`:

| Service | Port | Image | Restart |
|---------|------|-------|---------|
| dashboard | 8014 | `hth-dashboard:latest` | unless-stopped |
| postgresql | 5433 | `postgres:16-alpine` | unless-stopped |

Additional project services (your own apps) are added to the same compose file.

### Infrastructure services (bare, intentionally)

These are machine-level infrastructure, not project workloads:

| Service | Role | Why bare |
|---------|------|----------|
| Apache/nginx | TLS termination, reverse proxy | Must serve HTTPS before Docker starts |
| cloudflared (optional) | Cloudflare tunnel | Network infrastructure, not an application |

### Terminology: "build" vs "deploy"

- **Build (code)** = writing Python/JS code, running tests, committing. Happens on the laptop (Claude Code, local dev).
- **Build (image)** = `docker compose build` on the server. Creates a Docker image from the committed code.
- **Deploy** = `docker compose up -d` on the server. Starts or replaces running containers with the newly built images.

### Deployment workflow

```
Developer (laptop)                    Server
    |                                     |
    |-- git push -----------------------> |
    |                                     |-- git pull
    |                                     |-- docker compose build --build-arg GIT_COMMIT=$(git rev-parse HEAD)
    |                                     |-- docker compose up -d   (zero-downtime swap)
    |                                     |
    |                          Dashboard reads GIT_COMMIT from env
    |                          /health/deployment compares against git HEAD
    |                          "deployed" = container commit == latest main
```

### Zero-downtime image swap

Services must not go offline while a new image is being built or deployed:

- **Build before stop**: `docker compose build` creates the new image while the old container keeps running. Only `docker compose up -d` swaps them.
- **Health checks**: Containers define `HEALTHCHECK` so compose knows when the new container is ready before routing traffic.
- **Rolling updates**: `docker compose up -d --no-deps <service>` to update one service at a time.

### Networking

- Docker bridge network `hth-net` connects all containers
- Dashboard container connects to PostgreSQL via Docker DNS (`postgresql:5432`)
- Reverse proxy routes to container ports on `localhost` (mapped via Docker)
- No `host` network mode — containers expose only needed ports

### GIT_COMMIT tracking

Each image gets `GIT_COMMIT` baked in at build time:

```dockerfile
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
```

Built with: `docker compose build --build-arg GIT_COMMIT=$(git rev-parse HEAD)`

### Lock-down workflow

```bash
# Free the machine
docker compose down          # All project services stop

# Resume project work
docker compose up -d         # Everything comes back
```

## Prerequisites

- spec:014 (Autonomous Runtime) — runtime server must be containerizable
- spec:015 (Dashboard) — dashboard is the primary service to containerize
- spec:026 (Ground Truth) — deployment status depends on GIT_COMMIT mechanism

## Done When

- [x] `docker-compose.yml` in the repo defines core platform services (dashboard, PostgreSQL)
- [x] Dashboard runs inside a Docker container with `GIT_COMMIT` baked at build time
- [ ] `docker compose down` stops all project services — nothing persists outside Docker
- [x] `docker compose up -d` starts all services and they communicate via Docker network
- [x] Dashboard container connects to PostgreSQL via Docker DNS, not localhost
- [x] Reverse proxy config proxies to container ports
- [ ] `/health/deployment` accurately reports container's baked GIT_COMMIT vs repo HEAD
- [ ] Deploying a new image does not take services offline — zero-downtime swap
