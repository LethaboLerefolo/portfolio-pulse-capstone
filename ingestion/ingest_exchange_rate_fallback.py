"""Fallback loader for the USD -> NGN rate, writing the same `exchange_rate` layout as the Airbyte connector.

Used when INGESTION_MODE=python.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

import requests

from common import build_dsn, connect, setup_logging

log = setup_logging()

API_URL = "https://www.currencyexchangetool.com/api/v1/convert"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS exchange_rate (
    _airbyte_raw_id         VARCHAR(36)  NOT NULL,
    _airbyte_extracted_at   TIMESTAMPTZ  NOT NULL,
    _airbyte_meta           JSONB,
    _airbyte_generation_id  BIGINT,
    "from"                  VARCHAR(8),
    "to"                    VARCHAR(8),
    rate                    DOUBLE PRECISION,
    amount                  DOUBLE PRECISION,
    result                  DOUBLE PRECISION,
    success                 BOOLEAN,
    "updatedAt"             TIMESTAMPTZ
);
"""

INSERT_SQL = """
INSERT INTO exchange_rate
    (_airbyte_raw_id, _airbyte_extracted_at, _airbyte_meta, _airbyte_generation_id,
     "from", "to", rate, amount, result, success, "updatedAt")
VALUES (%s, now(), %s, 0, %s, %s, %s, %s, %s, %s, %s);
"""


def _fetch_open_er_api(base: str, quote: str) -> dict:
    """Free, key-less provider (https://open.er-api.com). Daily-updated mid-market rates."""
    resp = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise ValueError(f"open.er-api error payload: {data}")
    rate = data["rates"].get(quote)
    if not rate or float(rate) <= 0:
        raise ValueError(f"open.er-api returned no usable {quote} rate")
    updated = datetime.fromtimestamp(data["time_last_update_unix"], tz=timezone.utc).isoformat()
    return {"success": True, "rate": float(rate), "amount": 1, "result": float(rate), "updatedAt": updated}


def _fetch_currencyexchangetool(base: str, quote: str) -> dict:
    """Provider used in the NaijaShop lecture (now requires payment - kept as a secondary)."""
    resp = requests.get(API_URL, params={"amount": 1, "from": base, "to": quote}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise ValueError(f"API returned an error payload: {data}")
    if not data.get("rate") or float(data["rate"]) <= 0:
        raise ValueError(f"API returned a non-positive rate: {data}")
    return data


PROVIDERS = (_fetch_open_er_api, _fetch_currencyexchangetool)


def fetch_rate(base: str, quote: str) -> dict:
    """Try each provider in order; fail loudly only if ALL of them fail."""
    errors = []
    for provider in PROVIDERS:
        try:
            data = provider(base, quote)
            log.info("FX rate from %s", provider.__name__)
            return data
        except Exception as exc:  # noqa: BLE001 - we report every failure below
            errors.append(f"{provider.__name__}: {exc}")
            log.warning("FX provider failed - %s", errors[-1])
    raise RuntimeError("all FX providers failed: " + " | ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="USD")
    parser.add_argument("--quote", default="NGN")
    parser.add_argument("--dsn")
    args = parser.parse_args()

    try:
        data = fetch_rate(args.base, args.quote)
    except Exception as exc:
        log.error("FX FETCH FAILED: %s", exc)
        sys.exit(1)

    updated_at = data.get("updatedAt") or datetime.now(timezone.utc).isoformat()
    log.info("1 %s = %s %s (as of %s)", args.base, data["rate"], args.quote, updated_at)

    try:
        conn = connect(build_dsn(args.dsn))
        with conn, conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            cur.execute(
                INSERT_SQL,
                (
                    str(uuid.uuid4()),
                    json.dumps({"source": "python_fallback"}),
                    args.base,
                    args.quote,
                    data["rate"],
                    data.get("amount", 1),
                    data.get("result", data["rate"]),
                    True,
                    updated_at,
                ),
            )
        conn.close()
    except Exception as exc:
        log.error("FX LOAD FAILED: %s", exc)
        sys.exit(1)
    log.info("Loaded 1 row into exchange_rate.")


if __name__ == "__main__":
    main()
