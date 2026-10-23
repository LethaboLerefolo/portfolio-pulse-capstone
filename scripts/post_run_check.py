"""Post-run guard: fail if mart_portfolio_daily is empty or stale (--max-age-days), or the USD/NGN totals are missing.

On success, prints the headline numbers and writes them to the GitHub Actions run summary.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
from common import build_dsn, connect  # noqa: E402

SQL = """
select position_date, total_market_value_usd, total_market_value_ngn, usd_ngn_rate, rate_basis,
       unrealized_gain_loss_usd, unrealized_gain_loss_pct, positions_held
from marts.mart_portfolio_daily
order by position_date desc
limit 1
"""


def evaluate(row, today: date, max_age_days: int) -> list[str]:
    """Return a list of problems (empty list = healthy). Pure function, unit-testable."""
    if row is None:
        return ["mart_portfolio_daily is empty"]
    position_date, usd, ngn, *_ = row
    problems = []
    age = (today - position_date).days
    if age > max_age_days:
        problems.append(f"latest portfolio value is {age} days old (limit {max_age_days}): {position_date}")
    if usd is None or float(usd) <= 0:
        problems.append(f"headline USD value invalid: {usd}")
    if ngn is None or float(ngn) <= 0:
        problems.append(f"headline NGN value invalid: {ngn}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn")
    parser.add_argument("--max-age-days", type=int, default=5)
    args = parser.parse_args()

    conn = connect(build_dsn(args.dsn))
    with conn.cursor() as cur:
        cur.execute(SQL)
        row = cur.fetchone()
    conn.close()

    problems = evaluate(row, date.today(), args.max_age_days)
    if problems:
        for p in problems:
            print(f"::error::{p}")
        return 1

    d, usd, ngn, rate, basis, gl, gl_pct, n = row
    summary = (
        f"### PortfolioPulse - {d}\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Portfolio value (USD) | ${float(usd):,.2f} |\n"
        f"| Portfolio value (NGN) | N{float(ngn):,.2f} |\n"
        f"| USD/NGN rate | {float(rate):,.2f} ({basis}) |\n"
        f"| Unrealised gain/loss | ${float(gl):,.2f} ({float(gl_pct):.2f}%) |\n"
        f"| Positions held | {n} |\n"
    )
    print(summary)
    print(f"::notice title=PortfolioPulse {d}::USD {float(usd):,.2f} | NGN {float(ngn):,.2f} | rate {float(rate):,.2f} ({basis}) | P&L {float(gl):,.2f} USD ({float(gl_pct):.2f}%) | positions {n}")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
