"""Shared helpers for the ingestion scripts: logging and the Neon connection (--dsn or NEON_* env vars)."""
from __future__ import annotations

import logging
import os
import sys


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("portfolio_pulse")


def build_dsn(cli_dsn: str | None = None) -> str:
    """Return a libpq connection string, preferring --dsn, then env vars."""
    if cli_dsn:
        return cli_dsn
    needed = ["NEON_HOST", "NEON_DB", "NEON_USER", "NEON_PASSWORD"]
    missing = [k for k in needed if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            "ERROR: no database credentials. Pass --dsn or set: " + ", ".join(missing)
        )
    sslmode = os.environ.get("NEON_SSLMODE", "require")
    return (
        f"dbname={os.environ['NEON_DB']} user={os.environ['NEON_USER']} "
        f"password={os.environ['NEON_PASSWORD']} host={os.environ['NEON_HOST']} "
        f"sslmode={sslmode}"
    )


def connect(dsn: str):
    import psycopg2  # imported lazily so pure-logic functions can be unit tested without it

    return psycopg2.connect(dsn)
