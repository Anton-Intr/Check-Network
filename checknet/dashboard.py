from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .storage import DEFAULT_DB_PATH, init_db


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Check Net Uptime</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f4;
      --ink: #20241f;
      --muted: #667067;
      --line: #d9ded7;
      --panel: #ffffff;
      --good: #1f8a5b;
      --bad: #c2412d;
      --accent: #2459a6;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    main {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 36px;
    }

    header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 46px);
      line-height: 1;
      letter-spacing: 0;
    }

    .subtitle {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 15px;
    }

    form {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }

    input, button {
      height: 38px;
      border-radius: 6px;
      border: 1px solid var(--line);
      font: inherit;
    }

    input {
      background: #fff;
      color: var(--ink);
      padding: 0 10px;
    }

    button {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      padding: 0 14px;
      cursor: pointer;
      font-weight: 700;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }

    .stat, .chart-wrap, .table-wrap {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }

    .stat {
      padding: 14px;
      min-height: 86px;
    }

    .label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
      letter-spacing: .04em;
    }

    .value {
      margin-top: 8px;
      font-size: 28px;
      font-weight: 800;
      line-height: 1;
    }

    .chart-wrap {
      padding: 14px;
      margin-bottom: 12px;
    }

    canvas {
      display: block;
      width: 100%;
      height: 360px;
    }

    .table-wrap {
      overflow: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }

    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 13px;
      white-space: nowrap;
    }

    th {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }

    tr:last-child td { border-bottom: 0; }
    .ok { color: var(--good); font-weight: 750; }
    .fail { color: var(--bad); font-weight: 750; }

    @media (max-width: 780px) {
      header { display: block; }
      form { justify-content: flex-start; margin-top: 16px; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      canvas { height: 300px; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Network Uptime</h1>
        <p class="subtitle">SQLite-backed connectivity checks, grouped by minute.</p>
      </div>
      <form id="filters">
        <label for="start">From</label>
        <input id="start" name="start" type="datetime-local">
        <label for="end">To</label>
        <input id="end" name="end" type="datetime-local">
        <button type="submit">Apply</button>
      </form>
    </header>

    <section class="stats">
      <div class="stat"><div class="label">Uptime</div><div class="value" id="uptime">-</div></div>
      <div class="stat"><div class="label">Checks</div><div class="value" id="checks">-</div></div>
      <div class="stat"><div class="label">Failures</div><div class="value" id="failures">-</div></div>
      <div class="stat"><div class="label">Avg latency</div><div class="value" id="latency">-</div></div>
    </section>

    <section class="chart-wrap">
      <canvas id="chart" width="1100" height="360" aria-label="Uptime chart"></canvas>
    </section>

    <section class="table-wrap">
      <table>
        <thead>
          <tr><th>Time</th><th>Target</th><th>Status</th><th>HTTP</th><th>Latency</th><th>Error</th></tr>
        </thead>
        <tbody id="recent"></tbody>
      </table>
    </section>
  </main>

  <script>
    const startInput = document.querySelector("#start");
    const endInput = document.querySelector("#end");
    const form = document.querySelector("#filters");
    const canvas = document.querySelector("#chart");
    const ctx = canvas.getContext("2d");

    function toDateTimeLocal(value) {
      const offsetMs = value.getTimezoneOffset() * 60 * 1000;
      return new Date(value.getTime() - offsetMs).toISOString().slice(0, 16);
    }

    function startOfToday() {
      const now = new Date();
      return new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
    }

    function endOfToday() {
      const start = startOfToday();
      return new Date(start.getTime() + 24 * 60 * 60 * 1000);
    }

    startInput.value = toDateTimeLocal(startOfToday());
    endInput.value = toDateTimeLocal(endOfToday());

    form.addEventListener("submit", event => {
      event.preventDefault();
      load();
    });

    window.addEventListener("resize", () => load());

    function pct(value) {
      return `${(value * 100).toFixed(2)}%`;
    }

    function localTime(value) {
      return new Date(value).toLocaleString();
    }

    function drawChart(points) {
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(720, Math.floor(rect.width * ratio));
      canvas.height = Math.floor(rect.height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

      const width = rect.width;
      const height = rect.height;
      const pad = { left: 46, right: 16, top: 18, bottom: 34 };
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, width, height);

      ctx.strokeStyle = "#d9ded7";
      ctx.lineWidth = 1;
      ctx.fillStyle = "#667067";
      ctx.font = "12px system-ui";
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + ((height - pad.top - pad.bottom) * i / 4);
        const value = 100 - i * 25;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
        ctx.fillText(`${value}%`, 8, y + 4);
      }

      if (!points.length) {
        ctx.fillStyle = "#667067";
        ctx.font = "16px system-ui";
        ctx.fillText("No checks for this range yet.", pad.left, height / 2);
        return;
      }

      const plotW = width - pad.left - pad.right;
      const plotH = height - pad.top - pad.bottom;
      const xFor = index => pad.left + (points.length === 1 ? 0 : plotW * index / (points.length - 1));
      const yFor = uptime => pad.top + plotH * (1 - uptime);

      ctx.beginPath();
      points.forEach((point, index) => {
        const x = xFor(index);
        const y = yFor(point.uptime);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = "#2459a6";
      ctx.lineWidth = 2.5;
      ctx.stroke();

      ctx.fillStyle = "#2459a6";
      points.forEach((point, index) => {
        const x = xFor(index);
        const y = yFor(point.uptime);
        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fill();
      });

      ctx.fillStyle = "#667067";
      ctx.font = "12px system-ui";
      const first = new Date(points[0].minute).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const last = new Date(points[points.length - 1].minute).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      ctx.fillText(first, pad.left, height - 10);
      ctx.textAlign = "right";
      ctx.fillText(last, width - pad.right, height - 10);
      ctx.textAlign = "left";
    }

    async function load() {
      const params = new URLSearchParams();
      if (startInput.value) params.set("start", new Date(startInput.value).toISOString());
      if (endInput.value) params.set("end", new Date(endInput.value).toISOString());

      const response = await fetch(`/api/summary?${params.toString()}`);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to load summary.");
      }

      document.querySelector("#uptime").textContent = data.total_checks ? pct(data.uptime) : "-";
      document.querySelector("#checks").textContent = data.total_checks.toLocaleString();
      document.querySelector("#failures").textContent = data.failed_checks.toLocaleString();
      document.querySelector("#latency").textContent = data.avg_latency_ms == null ? "-" : `${Math.round(data.avg_latency_ms)} ms`;

      drawChart(data.series);

      const rows = data.recent.map(row => `
        <tr>
          <td>${localTime(row.checked_at)}</td>
          <td>${row.target}</td>
          <td class="${row.ok ? "ok" : "fail"}">${row.ok ? "OK" : "Fail"}</td>
          <td>${row.status_code ?? ""}</td>
          <td>${row.latency_ms == null ? "" : `${row.latency_ms} ms`}</td>
          <td>${row.error ?? ""}</td>
        </tr>
      `).join("");
      document.querySelector("#recent").innerHTML = rows || `<tr><td colspan="6">No checks found.</td></tr>`;
    }

    load();
    setInterval(load, 5000);
  </script>
</body>
</html>
"""


def normalize_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds")


def range_bounds(start_value: str | None, end_value: str | None, day: str | None) -> tuple[str, str]:
    if start_value and end_value:
        start = normalize_iso(start_value)
        end = normalize_iso(end_value)
        if start >= end:
            raise ValueError("Range start must be before range end.")
        return start, end
    if start_value or end_value:
        raise ValueError("Both range endpoints are required.")

    if day:
        selected = date.fromisoformat(day)
    else:
        selected = datetime.now(UTC).date()

    start = datetime.combine(selected, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    return start.isoformat(timespec="milliseconds"), end.isoformat(timespec="milliseconds")


def fetch_summary(
    db_path: Path,
    start_value: str | None = None,
    end_value: str | None = None,
    day: str | None = None,
) -> dict[str, object]:
    start, end = range_bounds(start_value, end_value, day)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_checks,
                COALESCE(SUM(ok), 0) AS ok_checks,
                COALESCE(SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END), 0) AS failed_checks,
                AVG(latency_ms) AS avg_latency_ms
            FROM requests
            WHERE checked_at >= ? AND checked_at < ?
            """,
            (start, end),
        ).fetchone()

        series = conn.execute(
            """
            SELECT
                substr(checked_at, 1, 16) || ':00.000+00:00' AS minute,
                COUNT(*) AS total,
                SUM(ok) AS ok_count,
                AVG(latency_ms) AS avg_latency_ms
            FROM requests
            WHERE checked_at >= ? AND checked_at < ?
            GROUP BY substr(checked_at, 1, 16)
            ORDER BY minute
            """,
            (start, end),
        ).fetchall()

        recent = conn.execute(
            """
            SELECT checked_at, target, ok, status_code, latency_ms, error
            FROM requests
            WHERE checked_at >= ? AND checked_at < ?
            ORDER BY checked_at DESC
            LIMIT 200
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()

    total_checks = int(totals["total_checks"])
    ok_checks = int(totals["ok_checks"])
    return {
        "date_start": start,
        "date_end": end,
        "total_checks": total_checks,
        "ok_checks": ok_checks,
        "failed_checks": int(totals["failed_checks"]),
        "uptime": ok_checks / total_checks if total_checks else 0,
        "avg_latency_ms": totals["avg_latency_ms"],
        "series": [
            {
                "minute": row["minute"],
                "total": row["total"],
                "ok_count": row["ok_count"],
                "uptime": row["ok_count"] / row["total"] if row["total"] else 0,
                "avg_latency_ms": row["avg_latency_ms"],
            }
            for row in series
        ],
        "recent": [
            {
                "checked_at": row["checked_at"],
                "target": row["target"],
                "ok": bool(row["ok"]),
                "status_code": row["status_code"],
                "latency_ms": row["latency_ms"],
                "error": row["error"],
            }
            for row in recent
        ],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB_PATH

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_text(HTML, "text/html; charset=utf-8")
            return

        if parsed.path == "/api/summary":
            query = parse_qs(parsed.query)
            start = query.get("start", [None])[0] or None
            end = query.get("end", [None])[0] or None
            day = query.get("date", [None])[0] or None
            try:
                payload = fetch_summary(Path(self.db_path), start, end, day)
            except ValueError:
                self.send_json(
                    {"error": "Invalid range. Use ISO timestamps, or date=YYYY-MM-DD."},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            self.send_json(payload)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_text(self, body: str, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def run_dashboard(db_path: str | Path = DEFAULT_DB_PATH, host: str = "127.0.0.1", port: int = 8765) -> None:
    init_db(db_path)
    DashboardHandler.db_path = Path(db_path)
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
