#!/bin/bash
# Double-click this file to start the AgriGrant dashboard.

DIR="$(cd "$(dirname "$0")" && pwd)"

# Kill any previous server on port 7654
lsof -ti tcp:7654 | xargs kill -9 2>/dev/null

echo "Starting AgriGrant backend..."
cd "$DIR"
python3 server.py &
SERVER_PID=$!

# Wait until the server accepts connections (max 10s)
for i in $(seq 1 20); do
  if curl -s http://localhost:7654/api/dashboard >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo "Opening browser..."
open http://localhost:7654

echo ""
echo "AgriGrant is running at http://localhost:7654"
echo "Admin panel:  http://localhost:7654/admin.html"
echo ""
echo "Press Ctrl+C to stop the server."
wait $SERVER_PID
