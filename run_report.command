#!/bin/bash
# Double-click from Finder to launch the CMS SST report with live-refresh support.
cd "$(dirname "$0")"

# Kill any process already listening on port 8765
OLDPID=$(lsof -ti tcp:8765)
if [ -n "$OLDPID" ]; then
    echo "Stopping existing server (PID $OLDPID)..."
    kill "$OLDPID"
    sleep 1
fi

python3 cms_local_server.py
