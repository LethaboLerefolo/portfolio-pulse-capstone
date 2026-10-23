"""Trigger Airbyte Cloud syncs via the API and wait for each job to finish.

Fails if any job fails, is cancelled or times out, so dbt never builds on half-loaded data.
Auth: OAuth2 client credentials (AIRBYTE_CLIENT_ID / AIRBYTE_CLIENT_SECRET).
Run:  python scripts/airbyte_sync.py --connection-id <uuid> [--connection-id <uuid> ...]
Set each connection's schedule to Manual, or an overlapping run returns HTTP 409.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import requests

DEFAULT_API = "https://api.airbyte.com/v1"
TERMINAL_OK = {"succeeded"}
TERMINAL_BAD = {"failed", "cancelled", "incomplete"}


def get_token(api: str, client_id: str, client_secret: str) -> str:
    resp = requests.post(
        f"{api}/applications/token",
        json={"client_id": client_id, "client_secret": client_secret},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def run_sync(api: str, token: str, connection_id: str, timeout_s: int, poll_s: int) -> None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.post(
        f"{api}/jobs", headers=headers, json={"connectionId": connection_id, "jobType": "sync"}, timeout=30
    )
    if resp.status_code == 409:
        raise RuntimeError(
            f"Connection {connection_id} already has a sync running (HTTP 409). "
            "Set the connection schedule to Manual so only GitHub Actions triggers it."
        )
    resp.raise_for_status()
    job = resp.json()
    job_id = job["jobId"]
    print(f"[airbyte] connection {connection_id}: job {job_id} started (status={job.get('status')})", flush=True)

    deadline = time.monotonic() + timeout_s
    while True:
        status = requests.get(f"{api}/jobs/{job_id}", headers=headers, timeout=30)
        status.raise_for_status()
        body = status.json()
        state = str(body.get("status", "")).lower()
        if state in TERMINAL_OK:
            rows = body.get("rowsSynced")
            print(f"[airbyte] job {job_id} succeeded (rowsSynced={rows})", flush=True)
            return
        if state in TERMINAL_BAD:
            raise RuntimeError(f"Airbyte job {job_id} for connection {connection_id} ended as '{state}'")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Airbyte job {job_id} still '{state}' after {timeout_s}s")
        time.sleep(poll_s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connection-id", action="append", required=True, dest="connection_ids")
    parser.add_argument("--api-url", default=os.environ.get("AIRBYTE_API_URL", DEFAULT_API))
    parser.add_argument("--timeout", type=int, default=900, help="seconds to wait per job")
    parser.add_argument("--poll-interval", type=int, default=10)
    args = parser.parse_args()

    client_id = os.environ.get("AIRBYTE_CLIENT_ID")
    client_secret = os.environ.get("AIRBYTE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERROR: set AIRBYTE_CLIENT_ID and AIRBYTE_CLIENT_SECRET", file=sys.stderr)
        return 2

    try:
        token = get_token(args.api_url, client_id, client_secret)
        for connection_id in args.connection_ids:
            run_sync(args.api_url, token, connection_id, args.timeout, args.poll_interval)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
