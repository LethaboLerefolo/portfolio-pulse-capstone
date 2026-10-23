"""Synthetic raw data in the shape of the three real sources, for the local end-to-end test only.

Includes weekend trades, messy sheet text, identical twin trades, missing prices and FX gaps.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

TICKERS = {"AAPL": 190, "MSFT": 400, "NVDA": 120, "GOOGL": 170, "AMZN": 180, "JPM": 200, "KO": 62, "VOO": 500}
FIRST_DAY = date(2025, 2, 3)
LAST_DAY = date(2026, 10, 19)          # last weekday before "today" (2026-10-20)
KO_MISSING = {date(2026, 10, 14), date(2026, 10, 15)}
FX_START = date(2026, 9, 15)
FX_GAPS = {date(2026, 10, 6), date(2026, 10, 7)}   # Tue + Wed: real trading days with no observation


def make_prices(seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = [d.date() for d in pd.bdate_range(FIRST_DAY, LAST_DAY)]
    rows = []
    for ticker, start in TICKERS.items():
        px = float(start)
        for d in days:
            px *= float(np.exp(rng.normal(0.0004, 0.014)))
            if ticker == "KO" and d in KO_MISSING:
                continue
            rows.append((ticker, d, round(px, 4), int(rng.integers(1_000_000, 9_000_000))))
    return pd.DataFrame(rows, columns=["ticker", "price_date", "close_price", "volume"])


def make_trades() -> pd.DataFrame:
    """(raw_trade_date, raw_ticker, raw_shares, raw_price) as the Sheet would deliver them (text)."""
    rows = [
        ("2025-03-03", "AAPL", "10", "190.10"),
        ("2025-03-03", "VOO", "2", "505.00"),
        ("2025-03-08", "MSFT", "5", "$1,234.50"),   # Saturday + currency formatting
        ("2025-04-01", "VOO", "2", "498.20"),
        ("2025-05-01", "VOO", "2", "510.00"),
        ("2025-06-02", " nvda ", "40", "125.00"),    # whitespace + lowercase
        ("2025-06-02", "VOO", "2", "515.50"),
        ("2025-07-15", "GOOGL", "12", "172.30"),
        ("2025-08-01", "AMZN", "1,500", "181.00"),   # thousands separator (1500 shares)
        ("2025-09-10", "JPM", "8", "205.00"),
        ("2025-09-10", "JPM", "8", "205.00"),        # exact twin - must survive as 2 rows
        ("2025-11-03", "KO", "30", "61.50"),
        ("2026-01-05", "AAPL", "5", "230.00"),
        ("2026-02-02", "VOO", "2", "520.00"),
        ("2026-04-01", "MSFT", "3", "410.00"),
        ("2026-08-03", "NVDA", "10", "130.00"),
    ]
    return pd.DataFrame(rows, columns=["trade_date", "ticker", "shares_bought", "price_paid_usd"])


def make_fx(seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rate = 1500.0
    rows = []
    d = FX_START
    while d <= LAST_DAY + timedelta(days=1):          # includes weekend + "today"
        rate *= float(np.exp(rng.normal(0.0, 0.003)))
        if d not in FX_GAPS:
            rows.append((d, datetime(d.year, d.month, d.day, 6, 0, tzinfo=timezone.utc), round(rate, 4)))
            if d == date(2026, 10, 10):               # second sync the same day - the later one must win
                rate *= 1.01
                rows.append((d, datetime(d.year, d.month, d.day, 18, 0, tzinfo=timezone.utc), round(rate, 4)))
        d += timedelta(days=1)
    return pd.DataFrame(rows, columns=["rate_date", "updated_at", "rate"])


# --------------------------------------------------------------------------- #
# Loaders                                                                      #
# --------------------------------------------------------------------------- #
def load_all(conn, prices: pd.DataFrame, trades: pd.DataFrame, fx: pd.DataFrame) -> None:
    from psycopg2.extras import execute_values

    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO stock_prices (ticker, price_date, close_price, volume) VALUES %s",
            list(prices.itertuples(index=False, name=None)),
            page_size=2000,
        )
        extracted = datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc)
        cur.executemany(
            """INSERT INTO trade_log (_airbyte_raw_id, _airbyte_extracted_at, _airbyte_meta, _airbyte_generation_id,
                                      trade_date, ticker, shares_bought, price_paid_usd)
               VALUES (%s, %s, %s, 0, %s, %s, %s, %s)""",
            [(str(uuid.uuid4()), extracted, json.dumps({"changes": []}), *r) for r in trades.itertuples(index=False, name=None)],
        )
        cur.executemany(
            """INSERT INTO exchange_rate (_airbyte_raw_id, _airbyte_extracted_at, _airbyte_meta, _airbyte_generation_id,
                                          "from", "to", rate, amount, result, success, "updatedAt")
               VALUES (%s, %s, %s, 0, 'USD', 'NGN', %s, 1, %s, true, %s)""",
            [
                (str(uuid.uuid4()), r.updated_at, json.dumps({"changes": []}), r.rate, r.rate, r.updated_at)
                for r in fx.itertuples(index=False)
            ],
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# Independent oracle: recompute the expected answer in pandas, NOT in SQL      #
# --------------------------------------------------------------------------- #
def _d(x) -> Decimal:
    return Decimal(str(x))


def _q(x: Decimal) -> Decimal:
    """Round to cents the way Postgres numeric does (half away from zero)."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clean_trades(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.copy()
    out["ticker"] = out["ticker"].str.strip().str.upper()
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.date
    for col in ("shares_bought", "price_paid_usd"):
        out[col] = out[col].str.replace(r"[^0-9.\-]", "", regex=True).astype(float)
    return out


def expected_daily(prices: pd.DataFrame, trades: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    tr = clean_trades(trades)
    # FX: last observation of each UTC day, then as-of join; before the first observation use the first.
    obs = fx.sort_values("updated_at").groupby("rate_date")["rate"].last().sort_index()
    all_days = pd.date_range(tr["trade_date"].min(), LAST_DAY + timedelta(days=1), freq="D").date
    rate_by_day = {}
    last = obs.iloc[0]
    for d in all_days:
        if d in obs.index:
            last = obs[d]
        elif d < obs.index[0]:
            last = obs.iloc[0]
        rate_by_day[d] = float(last)
    tr["rate_at_trade"] = tr["trade_date"].map(rate_by_day)
    tr["cost_usd"] = [_q(_d(s) * _d(p)) for s, p in zip(tr["shares_bought"], tr["price_paid_usd"])]
    tr["cost_ngn"] = [_q(c * _d(r)) for c, r in zip(tr["cost_usd"], tr["rate_at_trade"])]

    trading_days = sorted(prices["price_date"].unique())
    px = {t: g.sort_values("price_date").set_index("price_date")["close_price"].astype(float) for t, g in prices.groupby("ticker")}
    first_buy = tr.groupby("ticker")["trade_date"].min()
    out = []
    for d in trading_days:
        usd = ngn = cost_usd = cost_ngn = Decimal(0)
        n = 0
        for ticker, fb in first_buy.items():
            if d < fb:
                continue
            held = tr[(tr["ticker"] == ticker) & (tr["trade_date"] <= d)]
            close = px[ticker][px[ticker].index <= d].iloc[-1]
            mv = _q(sum((_d(x) for x in held["shares_bought"]), Decimal(0)) * _d(close))
            usd += mv
            ngn += _q(mv * _d(rate_by_day[d]))
            cost_usd += sum(held["cost_usd"], Decimal(0))
            cost_ngn += sum(held["cost_ngn"], Decimal(0))
            n += 1
        if n:
            out.append((d, n, float(usd), float(cost_usd), float(ngn), float(cost_ngn), rate_by_day[d]))
    return pd.DataFrame(
        out,
        columns=["position_date", "positions_held", "usd", "cost_usd", "ngn", "cost_ngn", "rate"],
    )
