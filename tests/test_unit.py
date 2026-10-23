"""Unit tests for the Python layer. No network, no database.   Run:  pytest -q tests/test_unit.py"""
from __future__ import annotations

import json
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingestion"))
sys.path.insert(0, str(ROOT / "scripts"))

import airbyte_sync  # noqa: E402
import generate_trade_log  # noqa: E402
import ingest_stock_prices as isp  # noqa: E402
from ingest_trade_log_fallback import parse_sheet_values  # noqa: E402


# ---------------------------------------------------------------- yfinance parsing
def _wide(tickers, level_order, days=3):
    idx = pd.date_range("2026-10-12", periods=days, freq="B", tz="America/New_York")
    cols = pd.MultiIndex.from_product([tickers, ["Open", "Close", "Volume"]] if level_order == "ticker_first"
                                      else [["Open", "Close", "Volume"], tickers])
    data = {c: [10.0 + i for i in range(days)] for c in cols}
    return pd.DataFrame(data, index=idx)


@pytest.mark.parametrize("order", ["ticker_first", "price_first"])
def test_normalize_handles_both_multiindex_orders(order):
    out = isp.normalize(_wide(["AAPL", "MSFT"], order), ["AAPL", "MSFT"])
    assert set(out["ticker"]) == {"AAPL", "MSFT"}
    assert len(out) == 6
    assert list(out.columns) == ["ticker", "price_date", "close_price", "volume"]
    assert out["price_date"].iloc[0] == date(2026, 10, 12)       # tz stripped, plain date


def test_normalize_single_ticker_flat_columns():
    idx = pd.to_datetime(["2026-10-12", "2026-10-13"])
    raw = pd.DataFrame({"Close": [101.5, 102.5], "Volume": [10, 20]}, index=idx)
    out = isp.normalize(raw, ["KO"])
    assert out["ticker"].tolist() == ["KO", "KO"]
    assert out["close_price"].tolist() == [101.5, 102.5]


def test_normalize_drops_null_and_non_positive_closes():
    idx = pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-14"])
    raw = pd.DataFrame({"Close": [float("nan"), 0.0, 55.0], "Volume": [1, 2, 3]}, index=idx)
    out = isp.normalize(raw, ["KO"])
    assert out["close_price"].tolist() == [55.0]


def test_validate_fails_loudly_when_a_ticker_is_missing():
    out = isp.normalize(_wide(["AAPL"], "ticker_first"), ["AAPL", "MSFT"])
    with pytest.raises(RuntimeError, match="MSFT"):
        isp.validate(out, ["AAPL", "MSFT"])


def test_validate_fails_on_empty_frame():
    with pytest.raises(RuntimeError):
        isp.validate(isp.normalize(pd.DataFrame(), ["AAPL"]), ["AAPL"])


def test_load_tickers_ignores_comments_blanks_and_duplicates(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("# header\nAAPL  # apple\n\nmsft\nAAPL\n")
    assert isp.load_tickers(f) == ["AAPL", "MSFT"]
    assert isp.load_tickers(ROOT / "config" / "tickers.txt")      # the real file parses, 5-10 tickers
    assert 5 <= len(isp.load_tickers(ROOT / "config" / "tickers.txt")) <= 10


# ---------------------------------------------------------------- sheet parsing
def test_parse_sheet_values_skips_blank_rows_and_pads_short_rows():
    rows = parse_sheet_values([
        ["Trade_Date", "Ticker", "Shares_Bought", "Price_Paid_USD"],
        ["2026-01-05", "AAPL", "5", "230"],
        [],
        ["", " ", ""],
        ["2026-02-02", "VOO", "2"],           # trailing cell omitted by the Sheets API
    ])
    assert len(rows) == 2
    assert rows[1]["price_paid_usd"] == ""


def test_parse_sheet_values_requires_headers():
    with pytest.raises(ValueError, match="missing columns"):
        parse_sheet_values([["date", "ticker"], ["2026-01-05", "AAPL"]])
    with pytest.raises(ValueError):
        parse_sheet_values([])


# ---------------------------------------------------------------- trade generator
def test_trade_generator_is_deterministic_realistic_and_buys_voo_monthly():
    days = [d.date() for d in pd.bdate_range("2025-03-03", "2026-03-31")]
    prices = pd.DataFrame(
        [(t, d, 100.0 + i, 1) for t in isp.load_tickers(ROOT / "config" / "tickers.txt") for i, d in enumerate(days)],
        columns=["ticker", "price_date", "close_price", "volume"],
    )
    a = generate_trade_log.build_trades(prices, date(2025, 3, 1), date(2026, 3, 31), seed=7)
    b = generate_trade_log.build_trades(prices, date(2025, 3, 1), date(2026, 3, 31), seed=7)
    assert a.equals(b)
    voo = a[a["ticker"] == "VOO"]
    assert len(voo) == 13                                         # Mar-2025 .. Mar-2026, one per month
    assert (a["shares_bought"] > 0).all() and (a["price_paid_usd"] > 0).all()
    # price paid is the actual close on that date
    merged = a.merge(prices.assign(trade_date=prices["price_date"].astype(str)), on=["trade_date", "ticker"])
    assert (merged["price_paid_usd"] == merged["close_price"].round(2)).all()


# ---------------------------------------------------------------- airbyte trigger-and-wait
class _Stub(BaseHTTPRequestHandler):
    polls = {}
    behaviour = "succeed"

    def log_message(self, *a):  # silence
        pass

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        if self.path.endswith("/applications/token"):
            return self._send(200, {"access_token": "tok-123"})
        if self.path.endswith("/jobs"):
            assert self.headers["Authorization"] == "Bearer tok-123"
            if _Stub.behaviour == "conflict":
                return self._send(409, {"message": "running"})
            return self._send(200, {"jobId": 42, "status": "running", "connectionId": payload["connectionId"]})
        self._send(404, {})

    def do_GET(self):
        if self.path.endswith("/jobs/42"):
            _Stub.polls["n"] = _Stub.polls.get("n", 0) + 1
            if _Stub.polls["n"] < 2:
                return self._send(200, {"jobId": 42, "status": "running"})
            final = "failed" if _Stub.behaviour == "fail" else "succeeded"
            return self._send(200, {"jobId": 42, "status": final, "rowsSynced": 7})
        self._send(404, {})


@pytest.fixture()
def stub_api(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("AIRBYTE_CLIENT_ID", "id")
    monkeypatch.setenv("AIRBYTE_CLIENT_SECRET", "secret")
    _Stub.polls, _Stub.behaviour = {}, "succeed"
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def _run(api, *conns):
    argv = ["airbyte_sync.py", "--api-url", api, "--poll-interval", "0", "--timeout", "5"]
    for c in conns:
        argv += ["--connection-id", c]
    sys.argv = argv
    return airbyte_sync.main()


def test_airbyte_sync_waits_for_success(stub_api):
    assert _run(stub_api, "conn-a") == 0
    assert _Stub.polls["n"] >= 2          # it really polled until the job finished


def test_airbyte_sync_fails_loudly_when_job_fails(stub_api):
    _Stub.behaviour = "fail"
    assert _run(stub_api, "conn-a") == 1


def test_airbyte_sync_reports_409_conflict(stub_api):
    _Stub.behaviour = "conflict"
    assert _run(stub_api, "conn-a") == 1


def test_airbyte_sync_requires_credentials(stub_api, monkeypatch):
    monkeypatch.delenv("AIRBYTE_CLIENT_ID")
    assert _run(stub_api, "conn-a") == 2


# ---------------------------------------------------------------- post-run guard
def test_post_run_check_evaluate():
    import post_run_check as prc
    today = date(2026, 10, 20)
    good = (date(2026, 10, 19), 1000.0, 1_500_000.0, 1500.0, "observed", 10.0, 1.0, 5)
    assert prc.evaluate(good, today, 5) == []
    assert "empty" in prc.evaluate(None, today, 5)[0]
    stale = (date(2026, 10, 1), 1000.0, 1.0, 1500.0, "observed", 0, 0, 5)
    assert "days old" in prc.evaluate(stale, today, 5)[0]
    bad = (date(2026, 10, 19), 0, None, 1500.0, "observed", 0, 0, 5)
    assert len(prc.evaluate(bad, today, 5)) == 2
