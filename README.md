# Check Net

Lightweight internet connectivity monitor with SQLite storage and a local uptime dashboard.

The project uses only the Python standard library:

- `check-net service` fires a small batch of HTTP requests every second.
- `check-net once` runs one batch and exits.
- Each request result is written to SQLite with timestamp, target, status, latency, and error details.
- `check-net dashboard` serves a local date-time range-filterable visualization from that database.

## Requirements

- Python 3.11+
- uv

## Install

```powershell
uv sync
```

To expose `check-net` on your PATH so it can be run from any directory:

```powershell
uv tool install .
```

For editable local development:

```powershell
uv tool install --editable .
```

## Run the checker

```powershell
uv run check-net service
```

If you installed it as a tool, you can run the same commands directly from any path:

```powershell
check-net service
```

By default it checks:

- `https://www.google.com/generate_204`
- `https://www.cloudflare.com/cdn-cgi/trace`
- `https://www.microsoft.com/favicon.ico`

Use your own targets by repeating `--target`:

```powershell
uv run check-net service --db .\data\checknet.sqlite3 --target https://example.com --target https://cloudflare.com
```

Useful options:

```powershell
uv run check-net service --interval 1 --timeout 2
```

For a quick smoke test:

```powershell
uv run check-net once
```

## Open the dashboard

In another terminal:

```powershell
uv run check-net dashboard --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

The dashboard refreshes every five seconds and has date-time range inputs for filtering uptime and request details.

By default, all commands read and write the same per-user database, so `check-net service`
and `check-net dashboard` share records even when launched from different directories.
On Windows, the default is:

```text
%LOCALAPPDATA%\check-net\checknet.sqlite3
```

To use a specific database, pass `--db` to both commands or set `CHECK_NET_DB`:

```powershell
$env:CHECK_NET_DB = "C:\path\to\checknet.sqlite3"
check-net service
check-net dashboard
```

If you already have records in the old project-local `.\data\checknet.sqlite3`, either keep
using that file with `--db` / `CHECK_NET_DB`, or copy it to the default app data path.

## Query the database directly

```powershell
sqlite3 "$env:LOCALAPPDATA\check-net\checknet.sqlite3" "select checked_at, target, ok, status_code, latency_ms, error from requests order by checked_at desc limit 10;"
```
