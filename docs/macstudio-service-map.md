# Server Service Map

**Updated**: 2026-03-29

This documents the target architecture for a dedicated server (e.g., Mac Mini, MacStudio, VPS) running the Axiom platform. Adapt paths, ports, and domain names to your setup.

## Docker Compose Stack

All managed by a single `docker-compose.yml`. `docker compose down` stops them all.

| Service | Container | Port | Binding | Notes |
|---------|-----------|------|---------|-------|
| Dashboard | `hth-dashboard` | 8014 | `0.0.0.0` | FastAPI + Claude Code CLI. Proxy via Apache/nginx at `/dashboard/` |
| PostgreSQL | `hth-postgresql` | 5433 | `127.0.0.1` | PG16. Loopback only — not network-accessible |

Add your own project services to the compose file as needed.

## Bare Metal (survive `docker compose down`)

These are infrastructure services, not application workloads:

| Service | Port | Binding | Manager | Notes |
|---------|------|---------|---------|-------|
| Apache/nginx | 80, 443 | `*` | System service | TLS termination. Must serve before Docker starts |
| cloudflared (optional) | — | — | System service | Cloudflare tunnel for DNS |

## What Happens When Docker Stops

```
Stops:        Dashboard, PostgreSQL, all project services
Keeps running: Web server (Apache/nginx), tunnel (cloudflared)
```

The web server keeps listening on 80/443 and will proxy requests to ports that no longer respond — returning 502/503 errors. This is noisy but not a security risk (no backend = no data served).

## Security Recommendations

### 1. Kill switch for non-dev use

A single script that stops Docker and frees the machine:

```bash
#!/bin/bash
# kill-all-services.sh

docker compose -f /path/to/axiom/docker-compose.yml down
echo "All services stopped."
```

Restore:
```bash
#!/bin/bash
cd /path/to/axiom && docker compose up -d
```

### 2. Router port audit

Only ports 80 and 443 should be forwarded from your router. If any application ports (8002, 8003, 8014, etc.) are forwarded directly (bypassing TLS), they're exposed without encryption.

### 3. Bind non-proxied services to loopback

Services accessed via reverse proxy should bind to `127.0.0.1`, not `0.0.0.0`. This way, even if the router forwards those ports, they're unreachable. PostgreSQL already does this correctly.
