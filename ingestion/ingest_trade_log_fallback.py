"""Fallback loader for the Google Sheet trade log, writing the same `trade_log` layout as Airbyte.

Replaces the table contents in one transaction. Credentials: GOOGLE_SERVICE_ACCOUNT_JSON or --credentials.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import os
import sys
import uuid

from common import build_dsn, connect, setup_logging

log = setup_logging()

REQUIRED_COLUMNS = ["trade_date", "ticker", "shares_bought", "price_paid_usd"]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trade_log (
    _airbyte_raw_id         VARCHAR(36)  NOT NULL,
    _airbyte_extracted_at   TIMESTAMPTZ  NOT NULL,
    _airbyte_meta           JSONB,
    _airbyte_generation_id  BIGINT,
    trade_date              TEXT,
    ticker                  TEXT,
    shares_bought           TEXT,
    price_paid_usd          TEXT
);
"""


def fetch_public_rows(sheet_id: str, tab: str) -> list[dict]:
    """No credentials: read a sheet shared as 'anyone with the link can view' through its CSV endpoint."""
    import csv
    import io

    import requests

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
    resp = requests.get(url, params={"tqx": "out:csv", "sheet": tab}, timeout=30)
    resp.raise_for_status()
    if "text/csv" not in resp.headers.get("Content-Type", ""):
        raise RuntimeError("Sheet is not readable without credentials - share it as 'anyone with the link: Viewer'")
    return parse_sheet_values([row for row in csv.reader(io.StringIO(resp.text))])


def fetch_rows(sheet_id: str, cell_range: str, credentials_file: str | None) -> list[dict]:
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and not credentials_file:
        return fetch_public_rows(sheet_id, cell_range.split("!")[0])

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        creds = service_account.Credentials.from_service_account_info(
            json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]), scopes=scopes
        )
    elif credentials_file:
        creds = service_account.Credentials.from_service_account_file(credentials_file, scopes=scopes)
    else:  # unreachable: handled above
        raise SystemExit("ERROR: set GOOGLE_SERVICE_ACCOUNT_JSON or pass --credentials")

    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    values = (
        service.spreadsheets().values().get(spreadsheetId=sheet_id, range=cell_range).execute().get("values", [])
    )
    return parse_sheet_values(values)


def parse_sheet_values(values: list[list[str]]) -> list[dict]:
    """First row = header. Skips fully blank rows. Raises if a required column is absent."""
    if not values:
        raise ValueError("Sheet returned no rows - check the tab name, range and sharing settings")
    header = [h.strip().lower() for h in values[0]]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"Sheet header is missing columns {missing}; found {header}")
    rows = []
    for raw in values[1:]:
        if not any(str(cell).strip() for cell in raw):
            continue
        padded = list(raw) + [""] * (len(header) - len(raw))
        rows.append({h: str(v).strip() for h, v in zip(header, padded)})
    return rows


def load(dsn: str, rows: list[dict]) -> int:
    conn = connect(dsn)
    try:
        with conn, conn.cursor() as cur:  # single transaction = atomic overwrite
            cur.execute(CREATE_TABLE_SQL)
            cur.execute("DELETE FROM trade_log;")
            for row in rows:
                cur.execute(
                    """INSERT INTO trade_log
                       (_airbyte_raw_id, _airbyte_extracted_at, _airbyte_meta, _airbyte_generation_id,
                        trade_date, ticker, shares_bought, price_paid_usd)
                       VALUES (%s, now(), %s, 0, %s, %s, %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        json.dumps({"source": "python_fallback"}),
                        row["trade_date"],
                        row["ticker"],
                        row["shares_bought"],
                        row["price_paid_usd"],
                    ),
                )
    finally:
        conn.close()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet-id", default=os.environ.get("TRADE_LOG_SHEET_ID"))
    parser.add_argument("--range", default="trade_log!A1:D1000", help="tab name must be trade_log")
    parser.add_argument("--credentials", help="path to service-account JSON (local runs)")
    parser.add_argument("--dsn")
    args = parser.parse_args()
    try:
        if args.sheet_id:
            rows = fetch_rows(args.sheet_id, args.range, args.credentials)
            log.info("Read %d trades from the sheet", len(rows))
        else:
            # No sheet configured: use the committed CSV (same content that gets imported into the Sheet).
            import csv

            csv_path = Path(__file__).resolve().parent.parent / "data" / "trade_log.csv"
            log.warning("TRADE_LOG_SHEET_ID not set - reading %s", csv_path)
            with open(csv_path, newline="", encoding="utf-8") as fh:
                rows = parse_sheet_values([row for row in csv.reader(fh)])
        loaded = load(build_dsn(args.dsn), rows)
    except Exception as exc:
        log.error("TRADE LOG INGESTION FAILED: %s", exc)
        sys.exit(1)
    log.info("Loaded %d rows into trade_log.", loaded)


if __name__ == "__main__":
    main()
