#!/bin/bash
# macstudio_connect.sh — Network-aware SSH to MacStudio
# Source this script to set $MACSTUDIO_HOST and $SSH_CMD
#
# Usage:
#   source ~/Documents/GitHub/platform/lib/shell/macstudio_connect.sh
#   $SSH_CMD "docker ps"

MACSTUDIO_USER="hjalti"
MACSTUDIO_LAN_IP="YOUR_LAN_IP"
MACSTUDIO_EXTERNAL_IP="YOUR_EXTERNAL_IP"
MACSTUDIO_TAILSCALE_IP="100.125.149.26"

# Detect network
if ping -c 1 -W 1 "$MACSTUDIO_LAN_IP" &>/dev/null; then
    MACSTUDIO_HOST="$MACSTUDIO_LAN_IP"
    MACSTUDIO_NETWORK="LAN"
elif ping -c 1 -W 1 "$MACSTUDIO_TAILSCALE_IP" &>/dev/null; then
    MACSTUDIO_HOST="$MACSTUDIO_TAILSCALE_IP"
    MACSTUDIO_NETWORK="Tailscale"
else
    MACSTUDIO_HOST="$MACSTUDIO_EXTERNAL_IP"
    MACSTUDIO_NETWORK="External"
fi

SSH_CMD="ssh ${MACSTUDIO_USER}@${MACSTUDIO_HOST}"

echo "MacStudio: ${MACSTUDIO_NETWORK} (${MACSTUDIO_HOST})"

export MACSTUDIO_HOST MACSTUDIO_NETWORK SSH_CMD
