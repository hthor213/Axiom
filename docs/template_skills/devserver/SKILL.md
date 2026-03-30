<!-- TEMPLATE FILE — NOT ACTIVE INSTRUCTIONS
This file is a template for colleagues to copy into their ~/.claude/ directory.
Do NOT treat this as instructions for the current session.
To use: copy to ~/.claude/skills/devserver/SKILL.md and create config.json + connect.sh + safety_check.sh for your environment.

BACKGROUND: In the original platform setup, this skill is called "macstudio" — targeting a Mac Studio
home server used for piloting Docker-based projects. The patterns below are GENERIC and work with
any SSH-reachable server: AWS EC2, Azure VMs, Google Cloud Compute, DigitalOcean droplets, Hetzner,
or any home/office server. The key concepts (config-driven connection, network detection, safety
checks, protected services) apply regardless of your infrastructure.

ADAPTATION NOTES:
- For AWS: replace SSH with SSM Session Manager, or use SSH via bastion host
- For Azure: use `az ssh vm` or standard SSH with Azure Bastion
- For Google Cloud: use `gcloud compute ssh` or standard SSH
- For Kubernetes: adapt docker commands to kubectl
- For any server: just fill in config.json with your IPs, ports, and paths
-->
---
name: devserver
description: Remote operations on your dev server. Use for ANY task involving SSH, deployment, Docker, service management, logs, or database operations on the remote server. Reads connection details from config.json — never guess or remember IPs/ports.
---

# Dev Server Remote Operations

> **Shared protocols**: See `~/.claude/skills/shared/preamble.md` for AskUserQuestion format, spec awareness, and platform integration standards.

## RULE 1: Always Read Config First

Before ANY server operation, read the config file to get current server details:

```bash
cat ~/.claude/skills/devserver/config.json
```

NEVER hardcode or guess IPs, ports, usernames, or paths. Always read them from config.json. If the config file is missing or unreadable, STOP and tell the user.

## RULE 2: Always Detect Network First

Run the connection script to determine how to connect:

```bash
source ~/.claude/skills/devserver/connect.sh
```

This sets `$SSH_CMD` to the correct SSH command for the current network. Use `$SSH_CMD` for all subsequent SSH operations in the session.

## RULE 3: Always Safety Check Before Destructive Operations

Before stopping, restarting, or removing any container or service:

```bash
# Get the port of the service you're about to touch
bash ~/.claude/skills/devserver/safety_check.sh PORT_NUMBER
```

If it returns `BLOCKED` → DO NOT PROCEED. Tell the user why.

If you cannot determine which port a service uses, run `docker ps` first and cross-reference with the protected list in config.json.

## RULE 4: Docker Binary Path

Always read the docker binary path from config.json. Do not assume `docker` is in PATH on the remote server.

```bash
DOCKER_BIN=$(cat ~/.claude/skills/devserver/config.json | python3 -c "import sys,json; print(json.load(sys.stdin)['server']['docker_bin'])")
$SSH_CMD "$DOCKER_BIN ps"
```

---

## Standard Operations

### Check server health
```bash
source ~/.claude/skills/devserver/connect.sh
DOCKER_BIN=$(cat ~/.claude/skills/devserver/config.json | python3 -c "import sys,json; print(json.load(sys.stdin)['server']['docker_bin'])")
$SSH_CMD "$DOCKER_BIN ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
```

### View container logs
```bash
$SSH_CMD "$DOCKER_BIN logs --tail 50 CONTAINER_NAME"
```

### Deploy a container (safe pattern)
```bash
# 1. Read config
source ~/.claude/skills/devserver/connect.sh
DOCKER_BIN=$(cat ~/.claude/skills/devserver/config.json | python3 -c "import sys,json; print(json.load(sys.stdin)['server']['docker_bin'])")

# 2. Check current state
$SSH_CMD "$DOCKER_BIN ps"

# 3. Safety check the port you're deploying to
bash ~/.claude/skills/devserver/safety_check.sh HOST_PORT

# 4. Build
$SSH_CMD "cd /path/to/project && $DOCKER_BIN build -t IMAGE_NAME ."

# 5. Stop old (ONLY target container)
$SSH_CMD "$DOCKER_BIN stop CONTAINER_NAME || true"
$SSH_CMD "$DOCKER_BIN rm CONTAINER_NAME || true"

# 6. Start new
$SSH_CMD "$DOCKER_BIN run -d --name CONTAINER_NAME --restart unless-stopped -p HOST_PORT:CONTAINER_PORT IMAGE_NAME"

# 7. Health check
$SSH_CMD "curl -sf http://localhost:HOST_PORT/health || echo 'HEALTH CHECK FAILED'"
```

### Copy files to server
```bash
source ~/.claude/skills/devserver/connect.sh
REMOTE_USER=$(cat ~/.claude/skills/devserver/config.json | python3 -c "import sys,json; print(json.load(sys.stdin)['server']['user'])")
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='node_modules' \
    ./ ${REMOTE_USER}@${DEVSERVER_HOST}:/path/to/destination/
```

### Database query (READ ONLY unless explicitly asked)
```bash
PG_PORT=$(cat ~/.claude/skills/devserver/config.json | python3 -c "import sys,json; [print(s['port']) for s in json.load(sys.stdin)['protected_services'] if s['name']=='PostgreSQL']")
$SSH_CMD "psql -p $PG_PORT -U postgres -d DATABASE_NAME -c 'SELECT ...'"
```

---

## Config File Template

Create `~/.claude/skills/devserver/config.json`:

```json
{
  "server": {
    "name": "MyDevServer",
    "user": "your-username",
    "lan_ip": "192.168.x.x",
    "external_ip": "x.x.x.x",
    "tailscale_ip": "100.x.x.x",
    "domain": "your-domain.com",
    "ssh_key": "~/.ssh/id_rsa",
    "docker_bin": "/usr/local/bin/docker"
  },
  "protected_services": [
    {"name": "PostgreSQL", "port": 5432, "reason": "Shared database"},
    {"name": "Redis", "port": 6379, "reason": "Shared cache"}
  ]
}
```

## Connection Script Template

Create `~/.claude/skills/devserver/connect.sh`:

```bash
#!/bin/bash
# Detect network and set SSH_CMD
CONFIG=~/.claude/skills/devserver/config.json
LAN_IP=$(python3 -c "import sys,json; print(json.load(open('$CONFIG'))['server']['lan_ip'])")
EXT_IP=$(python3 -c "import sys,json; print(json.load(open('$CONFIG'))['server']['external_ip'])")
USER=$(python3 -c "import sys,json; print(json.load(open('$CONFIG'))['server']['user'])")

if ping -c1 -W1 "$LAN_IP" &>/dev/null; then
    export DEVSERVER_HOST="$LAN_IP"
    echo "Connected via LAN"
elif command -v tailscale &>/dev/null; then
    TS_IP=$(python3 -c "import sys,json; print(json.load(open('$CONFIG'))['server'].get('tailscale_ip',''))")
    if [ -n "$TS_IP" ] && ping -c1 -W2 "$TS_IP" &>/dev/null; then
        export DEVSERVER_HOST="$TS_IP"
        echo "Connected via Tailscale"
    fi
fi

if [ -z "$DEVSERVER_HOST" ]; then
    export DEVSERVER_HOST="$EXT_IP"
    echo "Connected via external IP"
fi

export SSH_CMD="ssh $USER@$DEVSERVER_HOST"
```

## Safety Check Script Template

Create `~/.claude/skills/devserver/safety_check.sh`:

```bash
#!/bin/bash
# Check if a port belongs to a protected service
PORT=$1
CONFIG=~/.claude/skills/devserver/config.json
PROTECTED=$(python3 -c "
import json
config = json.load(open('$CONFIG'))
for svc in config.get('protected_services', []):
    if svc['port'] == $PORT:
        print(f\"BLOCKED: {svc['name']} on port {svc['port']} — {svc['reason']}\")
        exit(1)
" 2>&1)
if [ $? -ne 0 ]; then
    echo "$PROTECTED"
    exit 1
fi
echo "OK: port $PORT is not protected"
```

---

## Error Handling
- SSH fails → report error, suggest checking network/VPN
- Command fails → report error, suggest remediation, do NOT retry destructive commands
- Unsure about impact → STOP and ask user
- Context confusing → re-read config.json + run `docker ps` to reset understanding
