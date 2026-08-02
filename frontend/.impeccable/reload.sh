#!/bin/bash
# Rebuild and restart the review preview server. The server imports
# dist/server/server.js at startup, so a build without a restart leaves it
# serving HTML that points at asset hashes the build just replaced.
set -e
cd "$(dirname "$0")/.."
npm run build >/dev/null 2>&1
PID=$(netstat -ano 2>/dev/null | grep ':4173' | grep LISTENING | awk '{print $5}' | head -1)
[ -n "$PID" ] && powershell -NoProfile -Command "Stop-Process -Id $PID -Force" 2>/dev/null || true
sleep 1
nohup node .impeccable/preview-server.mjs >/tmp/preview.log 2>&1 &
sleep 2
curl -s -o /dev/null -w "preview: %{http_code}\n" http://localhost:4173/
