"""
Platform Telegram Notifier — Send notifications via the shared Telegram bot.

Usage:
    from platform_telegram import notify
    notify("Deploy complete for your-project-api")

Or with custom bot token/chat ID:
    notifier = TelegramNotifier(bot_token="...", chat_id="...")
    notifier.send("Custom message")
"""

import os
import urllib.request
import urllib.parse
import json
from pathlib import Path


def _load_vault_credentials():
    """Try to load Telegram credentials from the platform vault."""
    vault_path = Path(__file__).parent.parent.parent / "credentials" / "vault.yaml"
    if vault_path.exists():
        try:
            import yaml
            with open(vault_path) as f:
                vault = yaml.safe_load(f)
            tg = vault.get("telegram", {})
            return tg.get("bot_token"), tg.get("chat_id")
        except Exception:
            pass
    return None, None


def _get_credentials():
    """Get Telegram credentials from env vars or vault."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        vault_token, vault_chat = _load_vault_credentials()
        bot_token = bot_token or vault_token
        chat_id = chat_id or vault_chat

    return bot_token, chat_id


class TelegramNotifier:
    def __init__(self, bot_token=None, chat_id=None):
        if bot_token and chat_id:
            self.bot_token = bot_token
            self.chat_id = chat_id
        else:
            self.bot_token, self.chat_id = _get_credentials()

        if not self.bot_token or not self.chat_id:
            raise ValueError(
                "Telegram credentials not found. Set TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID env vars, or ensure platform vault is decrypted."
            )

    def send(self, message, parse_mode="HTML"):
        """Send a Telegram message. Returns True on success."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = json.dumps({
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.status == 200
        except Exception as e:
            print(f"Telegram send failed: {e}")
            return False


# Module-level convenience function
_notifier = None

def notify(message, parse_mode="HTML"):
    """Send a Telegram notification using default credentials."""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier.send(message, parse_mode)
