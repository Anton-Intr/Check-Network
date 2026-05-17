from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .storage import DEFAULT_DB_PATH, init_db


DASHBOARD_HTML = Path(__file__).with_name("dashboard.html")


def read_dashboard_html() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


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

        all_time_totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_checks,
                COALESCE(SUM(ok), 0) AS ok_checks,
                COALESCE(SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END), 0) AS failed_checks
            FROM requests
            """
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
            LIMIT 10
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()

    total_checks = int(totals["total_checks"])
    ok_checks = int(totals["ok_checks"])
    all_time_total_checks = int(all_time_totals["total_checks"])
    all_time_ok_checks = int(all_time_totals["ok_checks"])
    return {
        "date_start": start,
        "date_end": end,
        "total_checks": total_checks,
        "ok_checks": ok_checks,
        "failed_checks": int(totals["failed_checks"]),
        "uptime": ok_checks / total_checks if total_checks else 0,
        "all_time": {
            "total_checks": all_time_total_checks,
            "ok_checks": all_time_ok_checks,
            "failed_checks": int(all_time_totals["failed_checks"]),
            "uptime": all_time_ok_checks / all_time_total_checks if all_time_total_checks else 0,
        },
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
            self.send_text(read_dashboard_html(), "text/html; charset=utf-8")
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
