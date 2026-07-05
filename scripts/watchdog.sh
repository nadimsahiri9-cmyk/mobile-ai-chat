#!/bin/bash
# Watchdog: relance Caddy et API si down
pgrep -f "caddy.*Caddyfile" > /dev/null || /home/node/bin/caddy run --config /home/node/.openclaw/workspace/Caddyfile &
pgrep -f "api-server.py" > /dev/null || python3 /home/node/.openclaw/workspace/scripts/api-server.py &
