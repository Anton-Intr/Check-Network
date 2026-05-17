from __future__ import annotations

import argparse
import concurrent.futures
import signal
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .storage import DEFAULT_DB_PATH, connect, init_db, insert_request


DEFAULT_TARGETS = (
    "https://www.google.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
    "https://www.microsoft.com/favicon.ico",
)


@dataclass(frozen=True)
class ProbeResult:
    checked_at: str
    target: str
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None


def check_target(target: str, timeout: float) -> ProbeResult:
    checked_at = datetime.now(UTC).isoformat(timespec="milliseconds")
    started = time.perf_counter()
    request = urllib.request.Request(
        target,
        headers={
            "User-Agent": "check-net/0.1",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as response:
            latency_ms = (time.perf_counter() - started) * 1000
            status_code = response.getcode()
            return ProbeResult(
                checked_at=checked_at,
                target=target,
                ok=200 <= status_code < 400,
                status_code=status_code,
                latency_ms=round(latency_ms, 2),
                error=None,
            )
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return ProbeResult(
            checked_at=checked_at,
            target=target,
            ok=False,
            status_code=exc.code,
            latency_ms=round(latency_ms, 2),
            error=str(exc.reason),
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return ProbeResult(
            checked_at=checked_at,
            target=target,
            ok=False,
            status_code=None,
            latency_ms=round(latency_ms, 2),
            error=f"{type(exc).__name__}: {exc}",
        )


class ConnectivityMonitor:
    def __init__(
        self,
        *,
        db_path: str | Path = DEFAULT_DB_PATH,
        targets: tuple[str, ...] = DEFAULT_TARGETS,
        interval: float = 1.0,
        timeout: float = 2.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.targets = targets
        self.interval = interval
        self.timeout = timeout
        self._stop = False

    def stop(self, *_args: object) -> None:
        self._stop = True

    def run_once(self) -> list[ProbeResult]:
        init_db(self.db_path)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(self.targets))) as executor:
            futures = [
                executor.submit(check_target, target, self.timeout)
                for target in self.targets
            ]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        with connect(self.db_path) as conn:
            for result in results:
                insert_request(conn, **result.__dict__)

        return results

    def run_forever(self) -> None:
        init_db(self.db_path)
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        max_workers = max(1, len(self.targets))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            while not self._stop:
                tick_started = time.perf_counter()
                futures = [executor.submit(check_target, target, self.timeout) for target in self.targets]
                results = [future.result() for future in concurrent.futures.as_completed(futures)]

                with connect(self.db_path) as conn:
                    for result in results:
                        insert_request(conn, **result.__dict__)

                ok_count = sum(1 for result in results if result.ok)
                print(
                    f"{datetime.now().isoformat(timespec='seconds')} "
                    f"{ok_count}/{len(results)} checks succeeded",
                    flush=True,
                )

                elapsed = time.perf_counter() - tick_started
                time.sleep(max(0.0, self.interval - elapsed))


def parse_targets(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return DEFAULT_TARGETS
    return tuple(value for value in values if value.strip())


def add_probe_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        help="URL to check. Repeat to check multiple targets.",
    )
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between batches.")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-request timeout in seconds.")
