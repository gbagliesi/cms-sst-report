#!/usr/bin/env python3
"""
Local development server for the CMS SST report.

Serves the report at http://localhost:8765/ and exposes a /refresh endpoint
that re-runs cms_site_report.py (using the article cache) and reloads the page.

Usage:
    python3 cms_local_server.py [--port N] [--days N]
"""

import argparse
import http.server
import json
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8765
REPORT_PATH  = Path("cms_local_report.html")


class ReportHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Suppress per-request logs; only print errors
        if args and str(args[1]) not in ('200', '304'):
            sys.stderr.write(f"[server] {fmt % args}\n")

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            if not REPORT_PATH.exists():
                self._respond(503, 'text/plain', b'Report not generated yet.')
                return
            content = REPORT_PATH.read_bytes()
            self._respond(200, 'text/html; charset=utf-8', content)

        elif self.path.startswith('/refresh'):
            print("[server] Refresh requested — regenerating report...", flush=True)
            cmd = ['python3', 'cms_site_report.py', '--out', str(REPORT_PATH)]
            if self.server.days:
                cmd += ['--days', str(self.server.days)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            ok  = result.returncode == 0
            msg = (result.stderr or '').strip()[-500:]
            if ok:
                print("[server] Report refreshed.", flush=True)
            else:
                print(f"[server] ERROR:\n{msg}", flush=True)
            resp = json.dumps({'status': 'ok' if ok else 'error', 'log': msg}).encode()
            self._respond(200, 'application/json', resp)

        else:
            self._respond(404, 'text/plain', b'Not found')

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Local CMS SST report server")
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--days', type=int, default=3,
                        help='Look-back window in days for report generation')
    args = parser.parse_args()

    # Generate initial report
    print("Generating initial report...", flush=True)
    cmd = ['python3', 'cms_site_report.py', '--out', str(REPORT_PATH),
           '--days', str(args.days)]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("[ERROR] Report generation failed. Check output above.", file=sys.stderr)
        sys.exit(1)

    url = f'http://localhost:{args.port}/'
    server = http.server.HTTPServer(('localhost', args.port), ReportHandler)
    server.days = args.days

    print(f"Serving at {url}")
    print("Press Ctrl+C to stop.\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == '__main__':
    main()
