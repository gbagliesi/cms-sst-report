#!/bin/bash
# Double-click from Finder to launch the CMS SST report with live-refresh support.
cd "$(dirname "$0")"
python3 cms_local_server.py
