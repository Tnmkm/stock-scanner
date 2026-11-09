"""Scanner B - 'Trend-join Long' on tickers produced by Scanner A.

Valid only after 10:00 ET. Entry signal when ALL pass:
  1. price > yesterday's daily high
  2. yesterday's close > 200-day SMA
  3. price > today's pre-market high AND > today's high of day (set before the current bar)

TradingView has no API for running scans from a script, so these exact rules are
computed here from Yahoo data; trend_join_long.pine is the same logic for TradingView charts/alerts.

    python strategy_scanner.py           # needs today's premarket_*.json
    python strategy_scanner.py --force   # ignore the 10:00 ET gate (testing)
"""
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime

import config as C
import market_data as md
import premarket_scanner as pa

log = logging.getLogger("scannerB")


def evaluate(ticker, daily, intra, today):
    """-> dict with 'passed' bool, the levels and failed reasons."""
    hist = md.before_today(daily, today)
    res = {"ticker": ticker, "passed": False, "fails": []}
    if len(hist) < C.SMA_LENGTH:
        res["fails"].append(f"only {len(hist)} daily bars (<{C.SMA_LENGTH})")
        return res
    y_high = float(hist["High"].iloc[-1])
    y_close = float(hist["Close"].iloc[-1])
    sma = float(hist["Close"].rolling(C.SMA_LENGTH).mean().iloc[-1])
    pm, rth = md.split_sessions(intra, today)
    if len(rth) < 2:
        res["fails"].append("not enough regular-session bars")
        return res
    price = float(rth["Close"].dropna().iloc[-1])
    hod_prior = float(rth["High"].iloc[:-1].max())
    pm_high = float(pm["High"].max()) if not pm.empty else None

    checks = {
        "price > yesterday high": price > y_high,
        "yesterday close > 200 SMA": y_close > sma,
        "price > pre-market high": pm_high is not None and price > pm_high,
        "price > high of day": price > hod_prior,
    }
    stop_ref = max(v for v in (y_high, pm_high, hod_prior) if v is not None)
    res.update({
        "price": round(price, 2), "yesterday_high": round(y_high, 2),
        "yesterday_close": round(y_close, 2), "sma200": round(sma, 2),
        "premarket_high": round(pm_high, 2) if pm_high else None,
        "hod_before_bar": round(hod_prior, 2),
        "stop_ref": round(stop_ref, 2),
        "risk_pct": round((price - stop_ref) / price * 100, 2),
        "fails": [k for k, ok in checks.items() if not ok],
    })
    res["passed"] = not res["fails"]
    return res


def tickers_from_scanner_a(today) -> list[str]:
    data = pa.load_today(today)
    if not data:
        return []
    if C.STRATEGY_TICKER_SOURCE == "latest":
        return [h["ticker"] for h in data["latest"]["hits"]]
    return data.get("all_tickers", [])


def scan(now: datetime | None = None, force=False) -> dict:
    """-> {'status': 'ok'|'waiting'|'no_input', 'hits': [...], 'checked': n}"""
    now = now or datetime.now(C.ET)
    today = now.date()
    if not force and now.time() < C.STRATEGY_START:
        return {"status": "waiting", "hits": [], "checked": 0}
    tickers = tickers_from_scanner_a(today)
    if not tickers:
        return {"status": "no_input", "hits": [], "checked": 0}
    daily = md.daily_bars(tickers, period="2y")
    intra = md.intraday_bars(tickers)
    evaluated = []
    for t in tickers:
        if t in daily and t in intra:
            try:
                evaluated.append(evaluate(t, daily[t], intra[t], today))
            except Exception as e:
                log.debug("skip %s: %s", t, e)
    hits = [e for e in evaluated if e["passed"]]
    save(now, evaluated)
    return {"status": "ok", "hits": hits, "checked": len(evaluated)}


def save(now, evaluated):
    C.RESULTS_DIR.mkdir(exist_ok=True)
    p = C.RESULTS_DIR / f"strategy_{now.date().isoformat()}.json"
    data = json.loads(p.read_text()) if p.exists() else {"date": now.date().isoformat(), "runs": []}
    data["runs"].append({
        "run_at": now.isoformat(timespec="seconds"),
        "hits": [e for e in evaluated if e["passed"]],
        "evaluated": evaluated,
    })
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    out = scan(force="--force" in sys.argv)
    print(out["status"], f"checked={out['checked']}")
    for h in out["hits"]:
        print(f"{h['ticker']:6} entry ${h['price']}  stop ref ${h['stop_ref']} (-{h['risk_pct']}%)")
