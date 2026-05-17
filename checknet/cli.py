from __future__ import annotations

import argparse

from .dashboard import run_dashboard
from .probe import ConnectivityMonitor, add_probe_args, parse_targets
from .storage import init_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check-net",
        description="Monitor internet connectivity and visualize uptime from SQLite.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    service = subparsers.add_parser("service", help="Run the background connectivity checker.")
    add_probe_args(service)

    once = subparsers.add_parser("once", help="Run one batch of connectivity checks and exit.")
    add_probe_args(once)

    dashboard = subparsers.add_parser("dashboard", help="Run the local visualization dashboard.")
    dashboard.add_argument("--db", default="checknet.sqlite3", help="SQLite database path.")
    dashboard.add_argument("--host", default="127.0.0.1", help="Bind host.")
    dashboard.add_argument("--port", type=int, default=8765, help="Bind port.")

    init = subparsers.add_parser("init-db", help="Create the SQLite database schema.")
    init.add_argument("--db", default="checknet.sqlite3", help="SQLite database path.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "service":
        monitor = ConnectivityMonitor(
            db_path=args.db,
            targets=parse_targets(args.targets),
            interval=args.interval,
            timeout=args.timeout,
        )
        monitor.run_forever()
        return

    if args.command == "once":
        monitor = ConnectivityMonitor(
            db_path=args.db,
            targets=parse_targets(args.targets),
            interval=args.interval,
            timeout=args.timeout,
        )
        for result in monitor.run_once():
            status = "OK" if result.ok else "FAIL"
            latency = f"{result.latency_ms:.2f} ms" if result.latency_ms is not None else "-"
            detail = result.status_code if result.status_code is not None else result.error
            print(f"{status:4} {latency:>10} {result.target} {detail}")
        return

    if args.command == "dashboard":
        run_dashboard(args.db, args.host, args.port)
        return

    if args.command == "init-db":
        init_db(args.db)
        print(f"Initialized {args.db}")
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
