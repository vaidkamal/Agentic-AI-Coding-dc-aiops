#!/usr/bin/env bash
# demo-tunnel.sh — temporary public URL for the LOCAL console via a Cloudflare Quick Tunnel.
#
# The course alternative to Phases 4–6 when no AWS account is at hand: the app keeps
# running on this machine (docker compose, port 8080); cloudflared opens an outbound
# connection and Cloudflare hands out a random https://<words>.trycloudflare.com URL.
#
# Usage:
#   docker compose up --build            # in another terminal; console on :8080
#   deploy/scripts/demo-tunnel.sh [port] # default 8080
#
# Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
#   macOS: brew install cloudflared     Debian/Ubuntu: apt install cloudflared (Cloudflare apt repo)

set -euo pipefail

PORT="${1:-8080}"

cat >&2 <<EOF
================================================================================
 Cloudflare Quick Tunnel -> http://localhost:$PORT
--------------------------------------------------------------------------------
 CONSTRAINTS (read before sharing the link):
  * TEMPORARY: the URL dies when this process stops; a new run gets a NEW random URL.
  * NO ACCOUNT, NO SLA: quick tunnels are for testing. Cloudflare may rate-limit or
    drop them; do not use for anything beyond a demo.
  * NO AUTH AT THE EDGE: anyone with the URL reaches the app. Keep AUTH_MODE=oidc, or
    accept that AUTH_MODE=dev means every visitor is 'dev-operator' who can create and
    resolve incidents. Never expose real ticketing credentials this way.
  * LOCAL DATA: incidents live in this machine's database (or memory); nothing here
    demonstrates Phase 7 backup/restore.
  * WEBSOCKETS: /ws/telemetry works through the tunnel; expect ~100-300 ms extra latency.
  * STOP with Ctrl-C when the demo ends.
================================================================================
EOF

command -v cloudflared >/dev/null || { echo "cloudflared not installed (see header)" >&2; exit 1; }

if ! curl -fsS --max-time 3 "http://localhost:$PORT/healthz" >/dev/null 2>&1; then
  echo "WARNING: nothing answers on http://localhost:$PORT/healthz - start the app first (docker compose up)" >&2
fi

# --no-autoupdate keeps the binary stable during the demo. The public URL is printed by
# cloudflared in its own log lines ("https://....trycloudflare.com").
exec cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT"
