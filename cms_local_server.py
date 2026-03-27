#!/usr/bin/env python3
"""
Local development server for the CMS SST report.

Serves the report at http://localhost:8765/ and exposes a /refresh endpoint
that re-runs cms_site_report.py (using the article cache) and reloads the page.

Usage:
    python3 cms_local_server.py [--port N] [--days N]
"""

import argparse
import hashlib
import http.server
import json
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path


def _file_hash(path):
    """MD5 of file contents, or empty string if file does not exist."""
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return ""

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
            old_hash = _file_hash(REPORT_PATH)
            cmd = ['python3', 'cms_site_report.py', '--out', str(REPORT_PATH)]
            if self.server.days:
                cmd += ['--days', str(self.server.days)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            ok      = result.returncode == 0
            msg     = (result.stderr or '').strip()[-500:]
            changed = ok and (_file_hash(REPORT_PATH) != old_hash)
            if ok:
                print(f"[server] Report refreshed ({'changed' if changed else 'no changes'}).",
                      flush=True)
            else:
                print(f"[server] ERROR:\n{msg}", flush=True)
            resp = json.dumps({
                'status':  'ok' if ok else 'error',
                'changed': changed,
                'log':     msg,
            }).encode()
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


def run_server(port=DEFAULT_PORT, days=3, open_browser=True, ready_event=None):
    """Start the report server (blocking). Can be called from external code.

    Args:
        port:         TCP port to listen on.
        days:         Default look-back window passed to cms_site_report.py.
        open_browser: If True, open the system browser after startup.
        ready_event:  Optional threading.Event set once the server socket is bound
                      and the initial report has been generated.
    """
    print("Generating initial report...", flush=True)
    cmd = ['python3', 'cms_site_report.py', '--out', str(REPORT_PATH),
           '--days', str(days)]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("[ERROR] Report generation failed. Check output above.", file=sys.stderr)
        return

    url = f'http://localhost:{port}/'
    server = http.server.HTTPServer(('localhost', port), ReportHandler)
    server.days = days

    print(f"Serving at {url}", flush=True)
    if open_browser:
        print("Press Ctrl+C to stop.\n")

    if ready_event is not None:
        ready_event.set()

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Local CMS SST report server")
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--days', type=int, default=3,
                        help='Look-back window in days for report generation')
    args = parser.parse_args()
    run_server(port=args.port, days=args.days, open_browser=True)


if __name__ == '__main__':
    main()
