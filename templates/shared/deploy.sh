#!/bin/bash
# Deploy to MacStudio
# Usage: ./deploy.sh

set -e

# Source platform network detection
PLATFORM_DIR="$HOME/Documents/GitHub/platform"
source "$PLATFORM_DIR/lib/shell/macstudio_connect.sh"

echo "Deploying to MacStudio ($MACSTUDIO_NETWORK)..."

# TODO: Customize these for your project
PROJECT_NAME="$(basename "$(pwd)")"
REMOTE_DIR="${HOME}/${PROJECT_NAME}-deploy"

# Sync files
rsync -avz --exclude '.git' --exclude 'node_modules' --exclude '__pycache__' --exclude '.venv' \
    ./ "${MACSTUDIO_USER}@${MACSTUDIO_HOST}:${REMOTE_DIR}/"

echo "Files synced to ${REMOTE_DIR}"

# TODO: Add your restart commands here
# $SSH_CMD "cd ${REMOTE_DIR} && docker compose up -d --build"

echo "Deploy complete!"
source "$PLATFORM_DIR/lib/shell/telegram.sh"
send_telegram "Deploy complete: ${PROJECT_NAME} to MacStudio ($MACSTUDIO_NETWORK)"
