"""Load daily closing prices for the tickers in config/tickers.txt into the raw `stock_prices` table.

Upserts on (ticker, price_date), so re-runs are safe. Uses unadjusted closes to match the prices in the trade log,
and exits non-zero if Yahoo returns nothing for a ticker.

    python ingestion/ingest_stock_prices.py                          # daily run, last 10 days
    python ingestion/ingest_stock_prices.py --backfill-from 2025-01-01   # one-off history load
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from common import build_dsn, connect, setup_logging

log = setup_logging()

DEFAULT_TICKER_FILE = Path(__file__).resolve().parent.parent / "config" / "tickers.txt"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_prices (
    ticker       VARCHAR(12)   NOT NULL,
    price_date   DATE          NOT NULL,
    close_price  NUMERIC(14,4) NOT NULL CHECK (close_price > 0),
    volume       BIGINT,
    loaded_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, price_date)
);
"""

UPSERT_SQL = """
INSERT INTO stock_prices (ticker, price_date, close_price, volume, loaded_at)
VALUES %s
ON CONFLICT (ticker, price_date) DO UPDATE SET
    close_price = EXCLUDED.close_price,
    volume      = EXCLUDED.volume,
    loaded_at   = now();
"""


# --------------------------------------------------------------------------- #
# Pure functions (unit-tested in tests/test_stock_ingestion.py - no network)  #
# --------------------------------------------------------------------------- #
def load_tickers(path: Path) -> list[str]:
    """Read one ticker per line; '#' starts a comment; duplicates are dropped."""
    tickers: list[str] = []
    for line in path.read_text().splitlines():
        symbol = line.split("#", 1)[0].strip().upper()
        if symbol and symbol not in tickers:
            tickers.append(symbol)
    if not tickers:
        raise ValueError(f"No tickers found in {path}")
    return tickers


def normalize(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Turn yfinance's wide frame into a long frame: ticker, price_date, close_price, volume.

    yfinance returns a column MultiIndex whose level order has changed between
    versions ((Price, Ticker) vs (Ticker, Price)); and a plain index for a single
    ticker. This handles all three shapes.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["ticker", "price_date", "close_price", "volume"])

    frames = []
    if isinstance(raw.columns, pd.MultiIndex):
        ticker_level = next(
            (
                lvl
                for lvl in range(raw.columns.nlevels)
                if set(tickers) & set(raw.columns.get_level_values(lvl))
            ),
            None,
        )
        if ticker_level is None:
            return pd.DataFrame(columns=["ticker", "price_date", "close_price", "volume"])
        available = set(raw.columns.get_level_values(ticker_level))
        for ticker in tickers:
            if ticker not in available:
                continue
            frames.append(_one_ticker(raw.xs(ticker, axis=1, level=ticker_level), ticker))
    else:
        if len(tickers) != 1:
            raise ValueError("Flat columns returned for multiple tickers - unexpected yfinance shape")
        frames.append(_one_ticker(raw, tickers[0]))

    if not frames:
        return pd.DataFrame(columns=["ticker", "price_date", "close_price", "volume"])
    return pd.concat(frames, ignore_index=True)


def _one_ticker(sub: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if "Close" not in sub.columns:
        raise ValueError(f"'Close' column missing for {ticker}; got {list(sub.columns)}")
    out = pd.DataFrame(
        {
            "close_price": pd.to_numeric(sub["Close"], errors="coerce"),
            "volume": pd.to_numeric(sub["Volume"], errors="coerce") if "Volume" in sub.columns else pd.NA,
        }
    )
    out = out.dropna(subset=["close_price"])
    out = out[out["close_price"] > 0]
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out["price_date"] = idx.date
    out["ticker"] = ticker
    return out[["ticker", "price_date", "close_price", "volume"]].reset_index(drop=True)


def validate(long_df: pd.DataFrame, tickers: list[str]) -> None:
    """Raise if any requested ticker returned no rows - never load a partial refresh quietly."""
    got = set(long_df["ticker"]) if not long_df.empty else set()
    missing = [t for t in tickers if t not in got]
    if missing:
        raise RuntimeError(
            f"No price rows returned for: {', '.join(missing)}. "
            "Check the symbol spelling, or Yahoo may be rate-limiting."
        )
    dupes = long_df.duplicated(["ticker", "price_date"]).sum()
    if dupes:
        raise RuntimeError(f"{dupes} duplicate (ticker, price_date) rows after normalisation")


# --------------------------------------------------------------------------- #
# I/O                                                                         #
# --------------------------------------------------------------------------- #
def download(tickers: list[str], start: date, end: date, retries: int = 3) -> pd.DataFrame:
    import yfinance as yf

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            raw = yf.download(
                tickers=tickers,
                start=start.isoformat(),
                end=end.isoformat(),  # yfinance 'end' is exclusive
                auto_adjust=False,
                group_by="ticker",
                progress=False,
                threads=False,
            )
            if raw is not None and not raw.empty:
                return raw
            last_error = RuntimeError("yfinance returned an empty frame")
        except Exception as exc:  # network / rate-limit errors
            last_error = exc
        wait = 5 * attempt
        log.warning("download attempt %s/%s failed (%s); retrying in %ss", attempt, retries, last_error, wait)
        time.sleep(wait)
    raise RuntimeError(f"yfinance download failed after {retries} attempts: {last_error}")


def upsert(dsn: str, long_df: pd.DataFrame) -> int:
    from psycopg2.extras import execute_values

    rows = [
        (r.ticker, r.price_date, float(r.close_price), None if pd.isna(r.volume) else int(r.volume))
        for r in long_df.itertuples(index=False)
    ]
    conn = connect(dsn)
    try:
        with conn, conn.cursor() as cur:  # `with conn` commits on success, rolls back on error
            cur.execute(CREATE_TABLE_SQL)
            execute_values(
                cur,
                UPSERT_SQL,
                rows,
                template="(%s, %s, %s, %s, now())",
                page_size=1000,
            )
    finally:
        conn.close()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers-file", type=Path, default=DEFAULT_TICKER_FILE)
    parser.add_argument("--lookback-days", type=int, default=10, help="days to refresh on each daily run")
    parser.add_argument("--backfill-from", type=date.fromisoformat, help="YYYY-MM-DD; overrides --lookback-days")
    parser.add_argument("--dsn", help="libpq connection string (default: NEON_* env vars)")
    parser.add_argument("--dry-run", action="store_true", help="download and validate, but do not write")
    args = parser.parse_args()

    tickers = load_tickers(args.tickers_file)
    start = args.backfill_from or (date.today() - timedelta(days=args.lookback_days))
    end = date.today() + timedelta(days=1)
    log.info("Fetching %d tickers (%s) from %s to %s", len(tickers), ",".join(tickers), start, end)

    try:
        raw = download(tickers, start, end)
        long_df = normalize(raw, tickers)
        validate(long_df, tickers)
    except Exception as exc:
        log.error("INGESTION FAILED: %s", exc)
        sys.exit(1)

    log.info("Normalised %d rows across %d tickers", len(long_df), long_df["ticker"].nunique())
    if args.dry_run:
        log.info("Dry run - nothing written.")
        return

    try:
        written = upsert(build_dsn(args.dsn), long_df)
    except Exception as exc:
        log.error("LOAD FAILED: %s", exc)
        sys.exit(1)
    log.info("Upserted %d rows into stock_prices.", written)


if __name__ == "__main__":
    main()
