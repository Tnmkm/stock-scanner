"""Market backdrop + earnings dates + position sizing.

- regime(): SPY / QQQ trend and VIX level -> Risk-on / Caution / Risk-off
- next_earnings(): upcoming earnings date per ticker (cached once per day)
- position_size(): shares to buy so a stop-out loses at most RISK_PER_TRADE_PCT of the account
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

import config as C
import market_data as md

log = logging.getLogger("context")


# ---------- market regime ----------
def _trend(df):
    c = df["Close"].dropna()
    price = float(c.iloc[-1])
    prev = float(c.iloc[-2]) if len(c) > 1 else price
    sma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
    sma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else None
    return {"price": round(price, 2), "day_pct": round((price / prev - 1) * 100, 2),
            "above50": sma50 is not None and price > sma50,
            "above200": sma200 is not None and price > sma200}


def classify(spy: dict, qqq: dict, vix: float | None) -> str:
    """Pure rule set (testable)."""
    if not spy["above200"] or (vix is not None and vix >= 30):
        return "Risk-off"
    if spy["above50"] and qqq["above50"] and (vix is None or vix < 20):
        return "Risk-on"
    return "Caution"


def regime() -> dict | None:
    try:
        data = md.daily_bars(["SPY", "QQQ", "^VIX"], period="1y")
        if "SPY" not in data or "QQQ" not in data:
            return None
        spy, qqq = _trend(data["SPY"]), _trend(data["QQQ"])
        vix = float(data["^VIX"]["Close"].dropna().iloc[-1]) if "^VIX" in data else None
        r = {"spy": spy, "qqq": qqq, "vix": round(vix, 1) if vix else None,
             "label": classify(spy, qqq, vix)}
        return r
    except Exception as e:
        log.warning("regime failed: %s", e)
        return None


REGIME_TH = {"Risk-on": "🟢 ตลาดขาขึ้น", "Caution": "🟡 ระวัง", "Risk-off": "🔴 ตลาดอ่อนแอ — ลดขนาดไม้"}


def regime_line(r: dict | None) -> str:
    if not r:
        return ""
    vix = f" | VIX {r['vix']}" if r.get("vix") else ""
    return (f"Market: {REGIME_TH[r['label']]} | SPY {r['spy']['day_pct']:+.1f}%"
            f" | QQQ {r['qqq']['day_pct']:+.1f}%{vix}")


# ---------- earnings ----------
def _cache_path(d: date):
    return C.RESULTS_DIR / f"earnings_{d.isoformat()}.json"


def _fetch_earnings(ticker) -> str | None:
    import yfinance as yf
    try:
        cal = yf.Ticker(ticker).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            d = dates[0]
            return (d if isinstance(d, date) else datetime.fromisoformat(str(d)).date()).isoformat()
    except Exception as e:
        log.debug("earnings %s: %s", ticker, e)
    return None


def next_earnings(tickers: list[str], today: date) -> dict[str, str]:
    """{ticker: 'YYYY-MM-DD'} for tickers with a known upcoming date (cached per day)."""
    p = _cache_path(today)
    cache = json.loads(p.read_text()) if p.exists() else {}
    changed = False
    for t in tickers:
        if t not in cache and not t.startswith("^"):
            cache[t] = _fetch_earnings(t)
            changed = True
    if changed:
        C.RESULTS_DIR.mkdir(exist_ok=True)
        p.write_text(json.dumps(cache))
    return {t: cache[t] for t in tickers if cache.get(t)}


def earnings_soon(ed: str | None, today: date, days: int | None = None) -> int | None:
    """Days until earnings if within the warning window, else None."""
    if not ed:
        return None
    n = (date.fromisoformat(ed) - today).days
    return n if 0 <= n <= (days if days is not None else C.EARNINGS_WARN_DAYS) else None


# ---------- sizing ----------
def position_size(entry: float, stop: float) -> dict | None:
    """Shares so that (entry - stop) * shares = account * risk%. Capped by account size."""
    acct = C.ACCOUNT_SIZE_USD
    if not acct or entry <= 0 or stop >= entry:
        return None
    risk_usd = acct * C.RISK_PER_TRADE_PCT / 100
    shares = risk_usd / (entry - stop)
    shares = min(shares, acct * C.MAX_POSITION_PCT / 100 / entry)   # cap position size
    shares = round(shares, 2) if shares < 10 else int(shares)
    return {"shares": shares, "risk_usd": round(min(risk_usd, shares * (entry - stop)), 2),
            "cost_usd": round(shares * entry, 2)}
