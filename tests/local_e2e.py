"""Local end-to-end test of the transformation layer; needs a local Postgres.

Checks that dbt run/test pass on messy synthetic data, that the marts match an independent pandas calculation,
and that bad input (typo ticker, non-ISO date, negative price) fails loudly.
Env: LOCAL_PG_HOST, LOCAL_PG_PORT, LOCAL_PG_USER, LOCAL_PG_DB.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = ROOT / "portfolio_pulse_dbt"

HOST = os.environ.get("LOCAL_PG_HOST", "localhost")
PORT = os.environ.get("LOCAL_PG_PORT", "5433")
USER = os.environ.get("LOCAL_PG_USER", "postgres")
DB = os.environ.get("LOCAL_PG_DB", "portfolio_test")


def connect(dbname: str):
    conn = psycopg2.connect(host=HOST, port=PORT, user=USER, dbname=dbname)
    conn.autocommit = True
    return conn


def fresh_database() -> None:
    admin = connect("postgres")
    with admin.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {DB}")
    admin.close()
    conn = connect(DB)
    with conn.cursor() as cur:
        cur.execute((ROOT / "sql" / "01_raw_schema.sql").read_text())
    conn.close()


def dbt(*args: str, expect_ok: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "DBT_TARGET": "local", "LOCAL_PG_HOST": HOST, "LOCAL_PG_PORT": PORT,
           "LOCAL_PG_USER": USER, "LOCAL_PG_DB": DB, "DBT_PROFILES_DIR": str(DBT_DIR)}
    res = subprocess.run(["dbt", *args, "--no-use-colors"], cwd=DBT_DIR, env=env, capture_output=True, text=True)
    tail = "\n".join(res.stdout.strip().splitlines()[-14:])
    status = "OK " if res.returncode == 0 else "ERR"
    print(f"[dbt {' '.join(args)}] exit={res.returncode} {status}\n{tail}\n")
    if expect_ok and res.returncode != 0:
        print(res.stderr[-2000:])
        sys.exit(f"FAILED: dbt {' '.join(args)}")
    if not expect_ok and res.returncode == 0:
        sys.exit(f"FAILED: dbt {' '.join(args)} should have failed but passed")
    return res


def query(sql: str) -> pd.DataFrame:
    conn = connect(DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [c.name for c in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        conn.close()


def main() -> None:
    print("=== 1. build raw layer with synthetic data ===")
    fresh_database()
    prices, trades, fx = synthetic.make_prices(), synthetic.make_trades(), synthetic.make_fx()
    conn = psycopg2.connect(host=HOST, port=PORT, user=USER, dbname=DB)
    synthetic.load_all(conn, prices, trades, fx)
    conn.close()
    print(f"prices={len(prices)} trades={len(trades)} fx_rows={len(fx)}\n")

    print("=== 2. dbt: source gate -> run -> test ===")
    dbt("debug")
    dbt("test", "--select", "source:raw")          # quality gate BEFORE building anything
    dbt("run")
    dbt("test")

    print("=== 3. numbers vs independent pandas oracle ===")
    got = query("select * from marts.mart_portfolio_daily order by position_date")
    want = synthetic.expected_daily(prices, trades, fx)
    got["position_date"] = pd.to_datetime(got["position_date"]).dt.date
    merged = got.merge(want, on="position_date", how="outer", indicator=True, suffixes=("", "_oracle"))
    assert (merged["_merge"] == "both").all(), f"date mismatch:\n{merged[merged['_merge'] != 'both'][['position_date', '_merge']]}"
    checks = {
        "total_market_value_usd": "usd", "total_cost_basis_usd": "cost_usd",
        "total_market_value_ngn": "ngn", "total_cost_basis_ngn": "cost_ngn", "usd_ngn_rate": "rate",
    }
    for dbt_col, oracle_col in checks.items():
        diff = (merged[dbt_col].astype(float) - merged[oracle_col].astype(float)).abs().max()
        assert diff <= 0.0001, f"{dbt_col} differs from oracle by up to {diff}"
        print(f"  {dbt_col:<26} max |dbt - oracle| = {diff:.6f}  OK")
    assert (merged["positions_held"].astype(int) == merged["positions_held_oracle"].astype(int)).all()
    print(f"  {len(got)} trading days verified; positions_held matches\n")

    print("=== 4. behaviour checks ===")
    basis = query("select rate_basis, count(*) n from marts.mart_portfolio_daily group by 1 order by 1")
    print(basis.to_string(index=False))
    assert set(basis["rate_basis"]) >= {"backfilled", "observed", "carried_forward"}
    twins = query("select count(*) n, count(distinct trade_id) d from staging.stg_trades where ticker='JPM'")
    assert int(twins.n[0]) == 2 and int(twins.d[0]) == 2, "identical twin trades must both survive with unique ids"
    sat = query("select first_trade from (select min(position_date) first_trade from marts.mart_portfolio_value where ticker='MSFT') s")
    print(f"  MSFT bought Sat 2025-03-08 -> first valued {sat.first_trade[0]} (next trading day)")
    assert str(sat.first_trade[0]) == "2025-03-10"
    stale = query("select count(*) n from marts.mart_portfolio_value where is_stale_price and ticker='KO'")
    assert int(stale.n[0]) == 2, "KO has two missing days -> exactly two carried-forward prices"
    alloc = query("select round(sum(allocation_pct),1) s from marts.mart_current_positions")
    assert float(alloc.s[0]) == 100.0
    print("  twins kept, weekend trade deferred, stale prices flagged, allocation = 100%\n")

    print("=== 5. the pipeline must FAIL LOUDLY on bad data ===")
    conn = connect(DB)
    bad_cases = {
        "typo ticker 'APPL'": ("2026-09-01", "APPL", "3", "200", ["test", "--select", "assert_trade_tickers_have_prices"]),
        "US-style date 03/04/2025": ("03/04/2025", "AAPL", "3", "200", ["test", "--select", "source:raw"]),
        "negative price": ("2026-09-01", "AAPL", "3", "-5", ["test", "--select", "source:raw"]),
    }
    for label, (d, t, s, p, cmd) in bad_cases.items():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trade_log VALUES ('bad-row', now(), '{}', 0, %s, %s, %s, %s)", (d, t, s, p)
            )
        if "assert_trade" in cmd[-1]:
            dbt("run", "--select", "staging+")  # typo ticker only shows up downstream of staging
        print(f"  -> injecting {label}")
        dbt(*cmd, expect_ok=False)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM trade_log WHERE _airbyte_raw_id = 'bad-row'")
    conn.close()
    dbt("run")
    dbt("test")                                     # healthy again after cleanup

    print("ALL END-TO-END CHECKS PASSED")


if __name__ == "__main__":
    main()
