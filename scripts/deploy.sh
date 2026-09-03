#!/usr/bin/env bash
#
# Deploy whatever is on origin/main. Runs ON the server.
#
#   ./scripts/deploy.sh          # rebuild only what changed
#   ./scripts/deploy.sh --all    # rebuild both services regardless
#
# The one rule worth knowing: a commit that only touches the backend does NOT
# restart the bridge. Restarting it drops the WhatsApp socket, and every
# message a patient sends during the reconnect is gone - Baileys is not a
# queue. So the two images are rebuilt independently, and the bridge is left
# alone unless whatsapp-bridge/ actually changed.
set -euo pipefail

cd "$(dirname "$0")/.."

BEFORE=$(git rev-parse HEAD)
git fetch --quiet origin main
AFTER=$(git rev-parse origin/main)

if [ "$BEFORE" = "$AFTER" ] && [ "${1:-}" != "--all" ]; then
    echo "already at $(git rev-parse --short HEAD) - nothing to deploy"
    exit 0
fi

echo "deploying $(git rev-parse --short "$BEFORE") -> $(git rev-parse --short "$AFTER")"

# A deploy target must match the remote exactly, so tracked files are reset
# rather than merged - a stray edit on the server would otherwise conflict and
# stall the deploy at 3am. .env and whatsapp-bridge/auth_info/ are untracked
# and are NOT touched by this.
git reset --hard --quiet "$AFTER"

CHANGED=$(git diff --name-only "$BEFORE" "$AFTER" || true)
SERVICES=""

if [ "${1:-}" = "--all" ]; then
    SERVICES="backend bridge"
else
    if echo "$CHANGED" | grep -qE '^(backend/|Dockerfile$)'; then
        SERVICES="$SERVICES backend"
    fi
    if echo "$CHANGED" | grep -qE '^whatsapp-bridge/'; then
        SERVICES="$SERVICES bridge"
    fi
    # Compose itself changing can alter either container's config.
    if echo "$CHANGED" | grep -qE '^docker-compose\.yml$'; then
        SERVICES="backend bridge"
    fi
fi

SERVICES=$(echo "$SERVICES" | xargs || true)

if [ -z "$SERVICES" ]; then
    echo "no service code changed - nothing rebuilt, bridge left connected"
    exit 0
fi

echo "rebuilding: $SERVICES"
# shellcheck disable=SC2086
docker compose up -d --build $SERVICES

# ---------------------------------------------------------------- health gate
# A deploy that leaves the API down is worse than one that never ran, because
# nobody looks until a dose is missed.
PORT="${HEALTH_PORT:-8000}"
echo "waiting for /api/health ..."
for i in $(seq 1 30); do
    BODY=$(curl -fsS -m 5 "http://127.0.0.1:${PORT}/api/health" 2>/dev/null || true)
    if [ -n "$BODY" ] && echo "$BODY" | grep -q '"status":"ok"'; then
        echo "$BODY" | python3 -c '
import json,sys
d = json.load(sys.stdin)
print(f"  status     {d[\"status\"]}")
print(f"  database   {d[\"database\"]}")
print(f"  scheduler  {d[\"scheduler\"]}  (lock: {d.get(\"scheduler_lock\")})")
print(f"  whatsapp   {d[\"whatsapp\"][\"state\"]}")
bad = []
if d["database"] != "connected":               bad.append("database")
if d["whatsapp"]["state"] != "connected":      bad.append("whatsapp")
if d.get("scheduler_lock") not in ("held",):   bad.append("scheduler_lock")
if bad:
    print("  DEGRADED: " + ", ".join(bad))
    sys.exit(2)
'
        echo "deploy ok"
        exit 0
    fi
    sleep 3
done

echo "FAILED: /api/health never came back. docker compose logs -f backend" >&2
exit 1
