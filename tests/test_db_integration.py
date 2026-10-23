"""Integration tests for the ingestion writers against a real (local) Postgres.
Skipped automatically when no local Postgres is reachable.   Run: pytest -q tests/test_db_integration.py"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingestion"))
import ingest_exchange_rate_fallback as fx_fb  # noqa: E402
import ingest_stock_prices as isp  # noqa: E402
import ingest_trade_log_fallback as tl_fb  # noqa: E402

DSN = (f"host={os.environ.get('LOCAL_PG_HOST', 'localhost')} port={os.environ.get('LOCAL_PG_PORT', '5433')} "
       f"user={os.environ.get('LOCAL_PG_USER', 'postgres')} dbname=postgres")


@pytest.fixture()
def dsn():
    try:
        admin = psycopg2.connect(DSN)
    except psycopg2.OperationalError:
        pytest.skip("no local postgres")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS ingest_test WITH (FORCE)")
        cur.execute("CREATE DATABASE ingest_test")
    admin.close()
    yield DSN.replace("dbname=postgres", "dbname=ingest_test")


def scalar(dsn, sql):
    with psycopg2.connect(dsn) as c, c.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def test_stock_upsert_is_idempotent_and_refreshes_values(dsn):
    df = pd.DataFrame({"ticker": ["AAPL", "AAPL"], "price_date": [date(2026, 10, 15), date(2026, 10, 16)],
                       "close_price": [250.1, 251.2], "volume": [1, 2]})
    assert isp.upsert(dsn, df) == 2
    df.loc[1, "close_price"] = 260.0                       # a corrected close arrives on re-run
    isp.upsert(dsn, df)
    assert scalar(dsn, "select count(*) from stock_prices") == 2          # no duplicates
    assert float(scalar(dsn, "select close_price from stock_prices where price_date='2026-10-16'")) == 260.0


def test_stock_upsert_rejects_non_positive_price(dsn):
    bad = pd.DataFrame({"ticker": ["AAPL"], "price_date": [date(2026, 10, 15)], "close_price": [-1.0], "volume": [1]})
    with pytest.raises(psycopg2.errors.CheckViolation):
        isp.upsert(dsn, bad)


def test_trade_log_load_is_a_full_overwrite(dsn):
    rows = [{"trade_date": "2026-01-05", "ticker": "AAPL", "shares_bought": "5", "price_paid_usd": "230"}]
    tl_fb.load(dsn, rows)
    tl_fb.load(dsn, rows + [{"trade_date": "2026-02-02", "ticker": "VOO", "shares_bought": "2", "price_paid_usd": "520"}])
    assert scalar(dsn, "select count(*) from trade_log") == 2             # replaced, not appended (3)


def test_trade_log_failed_load_rolls_back_and_keeps_old_data(dsn):
    good = [{"trade_date": "2026-01-05", "ticker": "AAPL", "shares_bought": "5", "price_paid_usd": "230"}]
    tl_fb.load(dsn, good)
    with pytest.raises(KeyError):                                          # 2nd row malformed mid-load
        tl_fb.load(dsn, [good[0], {"trade_date": "x"}])
    assert scalar(dsn, "select count(*) from trade_log") == 1             # old snapshot intact


def test_exchange_rate_fallback_row_matches_airbyte_column_contract(dsn):
    import json, uuid
    from common import connect
    conn = connect(dsn)
    with conn, conn.cursor() as cur:
        cur.execute(fx_fb.CREATE_TABLE_SQL)
        cur.execute(fx_fb.INSERT_SQL, (str(uuid.uuid4()), json.dumps({}), "USD", "NGN", 1512.34, 1, 1512.34, True,
                                       "2026-10-19T06:00:00Z"))
    conn.close()
    assert float(scalar(dsn, 'select rate from exchange_rate where "to"=\'NGN\'')) == 1512.34
    assert scalar(dsn, 'select "updatedAt" is not null from exchange_rate') is True
