# Project Claude Code Configuration

## Platform Integration

This project uses the platform repo at `~/Documents/GitHub/platform` for:
- Credentials: Managed via `.env.platform` → `hth-platform env generate`
- MacStudio access: `hth-platform ssh` or source `platform/lib/shell/macstudio_connect.sh`
- Notifications: `from platform_telegram import notify`
- Database: `from platform_db import get_connection_string`

## Common Commands

```bash
# Generate .env from platform vault
cd ~/Documents/GitHub/platform && python cli/platform_cli.py env generate -m /path/to/this/project/.env.platform -o /path/to/this/project/.env

# Check MacStudio services
cd ~/Documents/GitHub/platform && python cli/platform_cli.py status

# SSH to MacStudio
cd ~/Documents/GitHub/platform && python cli/platform_cli.py ssh
```
