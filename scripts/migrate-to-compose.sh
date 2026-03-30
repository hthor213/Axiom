#!/usr/bin/env bash
# migrate-to-compose.sh — One-time migration from standalone containers + tmux to unified compose
#
# What this does:
#   1. Stops the tmux dashboard session
#   2. Stops standalone Docker containers (PostgreSQL, golf-planner, image-resizer)
#   3. Builds and starts everything via docker compose
#
# Prerequisites:
#   - Run from the ai-dev-framework repo root on MacStudio
#   - .env file with POSTGRES_PASSWORD and other secrets
#   - PG_DATA_DIR set in .env pointing to existing PostgreSQL data
#
# Usage:
#   cd /path/to/ai-dev-framework
#   bash scripts/migrate-to-compose.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---- Preflight checks ----

if [ ! -f "docker-compose.yml" ]; then
    error "Run this from the ai-dev-framework repo root"
    exit 1
fi

if [ ! -f ".env" ]; then
    error "No .env file found. Create one with at least POSTGRES_PASSWORD and PG_DATA_DIR"
    exit 1
fi

# Source .env to check required vars
set -a; source .env; set +a

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
    error "POSTGRES_PASSWORD not set in .env"
    exit 1
fi

if [ -z "${PG_DATA_DIR:-}" ]; then
    warn "PG_DATA_DIR not set — will create new database at ./pg-data"
    warn "To reuse existing data, set PG_DATA_DIR=/path/to/postgresql-deploy/data in .env"
    read -p "Continue with fresh database? [y/N] " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || exit 1
fi

info "Starting migration to unified Docker Compose..."

# ---- Step 1: Stop tmux dashboard ----

if tmux has-session -t dashboard 2>/dev/null; then
    info "Stopping tmux dashboard session..."
    tmux kill-session -t dashboard
    info "Dashboard tmux session stopped"
else
    info "No tmux dashboard session found (already stopped)"
fi

# ---- Step 2: Stop standalone containers ----

for container in postgresql-github-knowledge golf-planner-api image-resizer-erna; do
    if docker ps -q --filter "name=$container" | grep -q .; then
        info "Stopping standalone container: $container"
        docker stop "$container"
        docker rm "$container"
        info "Removed: $container"
    else
        info "Container $container not running (skipped)"
    fi
done

# ---- Step 3: Build and start compose stack ----

GIT_COMMIT=$(git rev-parse HEAD)
export GIT_COMMIT

info "Building images (GIT_COMMIT=$GIT_COMMIT)..."
docker compose build --build-arg GIT_COMMIT="$GIT_COMMIT"

info "Starting compose stack..."
docker compose up -d

# ---- Step 4: Verify ----

info "Waiting for services to become healthy..."
sleep 10

echo ""
info "=== Container Status ==="
docker compose ps

echo ""
info "=== Health Checks ==="

# Dashboard
if curl -sf http://localhost:8014/health > /dev/null 2>&1; then
    info "Dashboard (8014): ${GREEN}healthy${NC}"
else
    warn "Dashboard (8014): not responding yet (may still be starting)"
fi

# PostgreSQL
if docker compose exec postgresql pg_isready -U postgres > /dev/null 2>&1; then
    info "PostgreSQL (5433): ${GREEN}healthy${NC}"
else
    warn "PostgreSQL (5433): not ready"
fi

# Golf planner
if curl -sf http://localhost:8002/api/v1/health > /dev/null 2>&1; then
    info "Golf Planner (8002): ${GREEN}healthy${NC}"
else
    warn "Golf Planner (8002): not responding"
fi

# Image resizer
if curl -sf http://localhost:8003/erna/health > /dev/null 2>&1; then
    info "Image Resizer (8003): ${GREEN}healthy${NC}"
else
    warn "Image Resizer (8003): not responding"
fi

echo ""
info "Migration complete. Verify at https://spliffdonk.com"
info ""
info "Commands:"
info "  docker compose ps          # Status"
info "  docker compose logs -f     # Follow logs"
info "  docker compose down        # Stop everything (free MacStudio)"
info "  docker compose up -d       # Start everything"
