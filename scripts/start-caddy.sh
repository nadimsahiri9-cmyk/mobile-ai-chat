#!/bin/bash
# Keep Caddy running in the container
PIDFILE=/tmp/caddy-status.pid

if [ -f "$PIDFILE" ]; then
    PID=$(cat $PIDFILE)
    if kill -0 $PID 2>/dev/null; then
        exit 0
    fi
fi

# Caddy pas en route, on le lance
nohup /home/node/bin/caddy run --config /home/node/.openclaw/workspace/Caddyfile &>/tmp/caddy.log &
echo $! > $PIDFILE