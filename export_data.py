"""Writes results/public_latest.json: market data only (no shares, no costs, no tokens).

Read by the online dashboard. Contains:
  regime            SPY / QQQ / VIX backdrop
  watchlist         price, day change, trend, RSI, 20-day support/resistance, 90-day closes,
                    next earnings and latest headline for each ticker in watchlist.txt
  scanner_a         latest pre-market gappers today
  scanner_b         latest Trend-join Long hits today

    python export_data.py
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import config as C
import market_context as mc
import market_data as md
import portfolio as P
from premarket_scanner import get_catalyst

log = logging.getLogger("export")
WATCHLIST_FILE = C.BASE_DIR / "watchlist.txt"
OUT = C.RESULTS_DIR / "public_latest.json"
KEEP = ("ticker", "price", "live", "day_change_pct", "sma20", "sma50", "sma200", "rsi14",
        "support_20d", "resistance_20d", "trend", "history")


def load_watchlist() -> list[str]:
    if WATCHLIST_FILE.exists():
        ts = [l.split("#")[0].strip().upper() for l in WATCHLIST_FILE.read_text().splitlines()]
        ts = [t for t in ts if t]
        if ts:
            return list(dict.fromkeys(ts))
    return [h["ticker"] for h in P.load_portfolio()]


def extra_stats(df, today) -> dict:
    """52-week range, period returns, volume, 1-year closes."""
    d = df.dropna(subset=["Close"])
    c = d["Close"]
    price = float(c.iloc[-1])

    def ret(n):
        return round((price / float(c.iloc[-1 - n]) - 1) * 100, 2) if len(c) > n else None

    prev_year = c[[ts.year < today.year for ts in c.index]]
    ytd = round((price / float(prev_year.iloc[-1]) - 1) * 100, 2) if len(prev_year) else None
    vol = d["Volume"].fillna(0)
    hi, lo = float(d["High"].max()), float(d["Low"].min())
    return {
        "high_52w": round(hi, 2), "low_52w": round(lo, 2),
        "pct_from_high": round((price / hi - 1) * 100, 2),
        "pct_from_low": round((price / lo - 1) * 100, 2),
        "ret_1w": ret(5), "ret_1m": ret(21), "ret_3m": ret(63), "ret_6m": ret(126), "ret_ytd": ytd,
        "volume": int(vol.iloc[-1]), "avg_volume_20": int(vol.tail(21).iloc[:-1].mean()) if len(vol) > 1 else None,
        "volatility_20": round(float(c.pct_change().tail(20).std() * (252 ** 0.5) * 100), 1) if len(c) > 21 else None,
        "history": [[ts.strftime("%Y-%m-%d"), round(float(v), 2)] for ts, v in c.tail(252).items()],
    }


def _latest(prefix, today):
    p = C.RESULTS_DIR / f"{prefix}_{today.isoformat()}.json"
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:
        return None


def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(C.ET)
    today = now.date()
    tickers = load_watchlist()
    daily = md.daily_bars(tickers, period="1y") if tickers else {}
    try:
        earn = mc.next_earnings(list(daily), today)
    except Exception:
        earn = {}
    rows = []
    for t in tickers:
        if t not in daily:
            continue
        try:
            s = P.analyze({"ticker": t, "shares": 0.0, "avg_cost": None, "stop": None,
                           "target": None, "note": ""}, daily[t], today)
        except Exception as e:
            log.warning("analyze %s: %s", t, e)
            continue
        r = {k: s.get(k) for k in KEEP}
        r.update(extra_stats(daily[t], today))
        r["earnings_date"] = earn.get(t)
        r["earnings_in_days"] = mc.earnings_soon(earn.get(t), today)
        r["news"], _ = get_catalyst(t)
        rows.append(r)

    pa = _latest("premarket", today)
    sb = _latest("strategy", today)
    a_run = pa["latest"] if pa else None
    b_run = sb["runs"][-1] if sb and sb.get("runs") else None
    out = {
        "as_of": now.isoformat(timespec="seconds"),
        "market_date": today.isoformat(),
        "trading_day": C.is_trading_day(today),
        "regime": mc.regime(),
        "watchlist": rows,
        "scanner_a": {"run_at": a_run["run_at"] if a_run else None,
                      "coverage_pct": a_run.get("coverage_pct") if a_run else None,
                      "hits": [{k: h.get(k) for k in ("ticker", "price", "gap_pct", "premarket_volume",
                                                      "premarket_high", "catalyst")}
                               for h in (a_run["hits"] if a_run else [])]},
        "scanner_b": {"run_at": b_run["run_at"] if b_run else None,
                      "checked": len(b_run.get("evaluated", [])) if b_run else 0,
                      "hits": [{k: h.get(k) for k in ("ticker", "price", "yesterday_high", "premarket_high",
                                                      "hod_before_bar", "sma200", "stop_ref", "risk_pct")}
                               for h in (b_run["hits"] if b_run else [])]},
    }
    C.RESULTS_DIR.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    log.info("wrote %s (%d watchlist, %d A, %d B)", OUT, len(rows),
             len(out["scanner_a"]["hits"]), len(out["scanner_b"]["hits"]))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    build()
