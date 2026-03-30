#!/bin/bash
# telegram.sh — Send Telegram notifications from shell scripts
#
# Usage:
#   source ~/Documents/GitHub/platform/lib/shell/telegram.sh
#   send_telegram "Deploy complete for golf-planner-api"

# Load from env or fall back to platform vault
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    VAULT_FILE="$(dirname "$(dirname "$(dirname "$0")")")/credentials/vault.yaml"
    if [ -f "$VAULT_FILE" ]; then
        TELEGRAM_BOT_TOKEN=$(grep "bot_token:" "$VAULT_FILE" | head -1 | awk -F'"' '{print $2}')
        TELEGRAM_CHAT_ID=$(grep "chat_id:" "$VAULT_FILE" | head -1 | awk -F'"' '{print $2}')
    fi
fi

send_telegram() {
    local message="$1"
    local parse_mode="${2:-HTML}"

    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
        echo "Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set" >&2
        return 1
    fi

    curl -s -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"${message}\",\"parse_mode\":\"${parse_mode}\"}" \
        > /dev/null

    return $?
}
