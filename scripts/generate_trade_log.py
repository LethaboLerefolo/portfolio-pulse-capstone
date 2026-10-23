"""Generate a trade log (data/trade_log.csv) priced at real Yahoo closes, for import into the Google Sheet.

    python scripts/generate_trade_log.py --start 2025-03-01 --seed 7

VOO is bought monthly; the other tickers get a few lump-sum buys. The same --seed gives the same file.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
from ingest_stock_prices import DEFAULT_TICKER_FILE, download, load_tickers, normalize  # noqa: E402

LUMP_SUM_BUDGET_USD = (800, 3000)  # per irregular buy
DCA_TICKER = "VOO"
DCA_SHARES = 2


def build_trades(prices: pd.DataFrame, start: date, end: date, seed: int) -> pd.DataFrame:
    """prices: long frame (ticker, price_date, close_price). Returns trade_log frame."""
    rng = random.Random(seed)
    prices = prices.copy()
    prices["price_date"] = pd.to_datetime(prices["price_date"]).dt.date
    window = prices[(prices["price_date"] >= start) & (prices["price_date"] <= end)]
    trades: list[dict] = []

    for ticker, grp in window.groupby("ticker"):
        grp = grp.sort_values("price_date")
        closes = dict(zip(grp["price_date"], grp["close_price"].astype(float)))
        days = list(closes)
        if not days:
            continue
        if ticker == DCA_TICKER:
            seen_months: set[tuple[int, int]] = set()
            for day in days:  # first trading day of every month
                key = (day.year, day.month)
                if key not in seen_months:
                    seen_months.add(key)
                    trades.append(_row(day, ticker, DCA_SHARES, closes[day]))
        else:
            for day in sorted(rng.sample(days, k=min(len(days), rng.randint(2, 3)))):
                budget = rng.uniform(*LUMP_SUM_BUDGET_USD)
                shares = max(1, int(budget // closes[day]))
                trades.append(_row(day, ticker, shares, closes[day]))

    out = pd.DataFrame(trades, columns=["trade_date", "ticker", "shares_bought", "price_paid_usd"])
    return out.sort_values(["trade_date", "ticker"]).reset_index(drop=True)


def _row(day: date, ticker: str, shares: int, close: float) -> dict:
    return {
        "trade_date": day.isoformat(),
        "ticker": ticker,
        "shares_bought": shares,
        "price_paid_usd": round(close, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 3, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=14))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("data/trade_log.csv"))
    args = parser.parse_args()

    tickers = load_tickers(DEFAULT_TICKER_FILE)
    raw = download(tickers, args.start - timedelta(days=5), args.end + timedelta(days=2))
    prices = normalize(raw, tickers)
    trades = build_trades(prices, args.start, args.end, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(args.out, index=False)
    cost = (trades["shares_bought"] * trades["price_paid_usd"]).sum()
    print(f"Wrote {len(trades)} trades across {trades['ticker'].nunique()} tickers -> {args.out} (total cost ${cost:,.0f})")


if __name__ == "__main__":
    main()
