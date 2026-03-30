#!/usr/bin/env python3
"""Local dashboard server for agent ops state and stale-task monitoring."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_ops_state import snapshot


def dashboard_html() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Agent Ops Dashboard</title>
  <style>
    body { font-family: Segoe UI, Arial, sans-serif; margin: 16px; background: #0f172a; color: #e2e8f0; }
    h1 { margin: 0 0 12px; }
    .row { display: flex; gap: 16px; margin-bottom: 16px; }
    .card { background: #111827; border: 1px solid #334155; border-radius: 8px; padding: 12px; min-width: 220px; }
    .meta { display: flex; gap: 12px; margin: 8px 0 16px; color: #93c5fd; font-size: 13px; }
    .banner { display: none; margin: 8px 0 16px; padding: 10px; border-radius: 8px; font-weight: 600; }
    .banner.ok { display: block; background: #052e16; border: 1px solid #14532d; color: #86efac; }
    .banner.warn { display: block; background: #3f1d1d; border: 1px solid #7f1d1d; color: #fecaca; }
    table { width: 100%; border-collapse: collapse; background: #111827; border: 1px solid #334155; }
    th, td { border-bottom: 1px solid #334155; padding: 8px; text-align: left; font-size: 13px; }
    th { background: #1f2937; }
    tr.stale-row { background: #2b0b0b; }
    .stale { color: #fca5a5; font-weight: 700; }
    .ok { color: #86efac; font-weight: 700; }
    code { color: #93c5fd; }
  </style>
</head>
<body>
  <h1>Agent Ops Dashboard</h1>
  <div class="row">
    <div class="card"><div>Generated</div><div id="generated">-</div></div>
    <div class="card"><div>Total Active</div><div id="total">0</div></div>
    <div class="card"><div>Stale Tasks</div><div id="stale">0</div></div>
  </div>
  <div class="meta">
    <div>Last Refresh: <span id="last_refresh">-</span></div>
    <div>Data Age: <span id="data_age">-</span></div>
    <div>Refresh Every: <span id="interval">5s</span></div>
  </div>
  <div id="banner" class="banner ok">No stale tasks detected.</div>
  <h2>Active Tasks</h2>
  <table>
    <thead><tr><th>Task</th><th>Owner</th><th>Age (min)</th><th>Heartbeat</th><th>Status</th></tr></thead>
    <tbody id="tasks"></tbody>
  </table>
  <h2>Agent Capacity</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Status</th><th>Capacity</th><th>Active</th></tr></thead>
    <tbody id="agents"></tbody>
  </table>
  <script>
    const refreshMs = 5000;
    document.getElementById('interval').textContent = `${Math.floor(refreshMs/1000)}s`;

    function fmtAgeSeconds(s) {
      if (s < 60) return `${s}s`;
      if (s < 3600) return `${Math.floor(s / 60)}m`;
      return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
    }

    async function refresh() {
      const res = await fetch('/api/state');
      const data = await res.json();
      document.getElementById('generated').textContent = data.generated_at;
      document.getElementById('last_refresh').textContent = new Date().toLocaleTimeString();
      document.getElementById('total').textContent = data.tasks.length;
      const staleCount = data.tasks.filter(t => t.stale).length;
      document.getElementById('stale').textContent = staleCount;
      const maxAge = data.tasks.length ? Math.max(...data.tasks.map(t => t.age_seconds || 0)) : 0;
      document.getElementById('data_age').textContent = fmtAgeSeconds(maxAge);

      const banner = document.getElementById('banner');
      if (staleCount > 0) {
        banner.className = 'banner warn';
        banner.textContent = `${staleCount} stale task(s) need attention.`;
      } else {
        banner.className = 'banner ok';
        banner.textContent = 'No stale tasks detected.';
      }

      const tb = document.getElementById('tasks');
      tb.innerHTML = '';
      data.tasks.forEach(t => {
        const tr = document.createElement('tr');
        if (t.stale) tr.className = 'stale-row';
        tr.innerHTML =
          `<td><code>${t.task_id}</code></td>` +
          `<td>${t.owner}</td>` +
          `<td>${Math.floor(t.age_seconds/60)}</td>` +
          `<td>${t.last_heartbeat}</td>` +
          `<td class="${t.stale ? 'stale' : 'ok'}">${t.stale ? 'STALE' : 'OK'}</td>`;
        tb.appendChild(tr);
      });

      const byOwner = data.active_by_owner || {};
      const ab = document.getElementById('agents');
      ab.innerHTML = '';
      (data.agents || []).forEach(a => {
        const tr = document.createElement('tr');
        tr.innerHTML =
          `<td>${a.id}</td>` +
          `<td>${a.provider}</td>` +
          `<td>${a.status}</td>` +
          `<td>${a.capacity}</td>` +
          `<td>${byOwner[a.id] || 0}</td>`;
        ab.appendChild(tr);
      });
    }
    refresh();
    setInterval(refresh, refreshMs);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    stale_minutes = 45

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = dashboard_html().encode("utf-8")
            self._write(HTTPStatus.OK, body, "text/html; charset=utf-8")
            return
        if self.path == "/api/state":
            body = json.dumps(snapshot(self.stale_minutes), indent=2).encode("utf-8")
            self._write(HTTPStatus.OK, body, "application/json; charset=utf-8")
            return
        self._write(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent dashboard HTTP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stale-minutes", type=int, default=45)
    parser.add_argument("--once-json", action="store_true", help="Print one JSON snapshot and exit.")
    args = parser.parse_args()

    if args.once_json:
        print(json.dumps(snapshot(args.stale_minutes), indent=2))
        return 0

    Handler.stale_minutes = args.stale_minutes
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[OK] Dashboard: http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
