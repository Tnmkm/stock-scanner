"""Scanner A - Pre-market gappers.

Filters: gap > MIN_GAP_PCT vs previous close, price > MIN_PRICE,
pre-market volume > MIN_PREMARKET_VOLUME. Prices from Yahoo Finance (yfinance),
one-sentence catalyst from Benzinga (falls back to Yahoo news without a key).
Each run is appended to results/premarket_YYYY-MM-DD.json.

    python premarket_scanner.py          # scan and print
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime

import requests
import yfinance as yf

import config as C
import market_data as md

log = logging.getLogger("scannerA")


# ---------- universe ----------
def load_universe() -> list[str]:
    tickers: set[str] = set()
    if C.UNIVERSE_FILE.exists():
        for line in C.UNIVERSE_FILE.read_text().splitlines():
            t = line.split("#")[0].strip().upper()
            if t:
                tickers.add(t)
    for screen in C.YAHOO_SCREENS:
        try:
            res = yf.screen(screen, count=C.SCREEN_COUNT)
            for q in res.get("quotes", []):
                sym = q.get("symbol", "")
                if sym and "." not in sym and "=" not in sym:
                    tickers.add(sym.upper())
        except Exception as e:
            log.warning("Yahoo screen %s failed: %s", screen, e)
    return sorted(tickers)


# ---------- catalyst ----------
def _one_sentence(text: str, limit: int = 180) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def get_catalyst(ticker: str) -> tuple[str, str]:
    """-> (sentence, source)."""
    if C.BENZINGA_API_KEY:
        try:
            r = requests.get(
                "https://api.benzinga.com/api/v2/news",
                params={"token": C.BENZINGA_API_KEY, "tickers": ticker,
                        "pageSize": 1, "displayOutput": "abstract", "sort": "created:desc"},
                headers={"accept": "application/json"}, timeout=10)
            r.raise_for_status()
            items = r.json()
            if items:
                it = items[0]
                return _one_sentence(it.get("title") or it.get("teaser", "")), "Benzinga"
        except Exception as e:
            log.warning("Benzinga failed for %s: %s", ticker, e)
    try:
        news = yf.Ticker(ticker).news or []
        if news:
            it = news[0]
            content = it.get("content", it)
            title = content.get("title") or content.get("summary") or ""
            if title:
                return _one_sentence(title), "Yahoo"
    except Exception as e:
        log.debug("Yahoo news failed for %s: %s", ticker, e)
    return "No recent news found.", "-"


# ---------- core filter (pure, testable) ----------
def evaluate(ticker, daily, intra, today):
    """Return a hit dict or None."""
    hist = md.before_today(daily, today)
    if hist.empty:
        return None
    prev_close = float(hist["Close"].iloc[-1])
    pm, rth = md.split_sessions(intra, today)
    bars = rth if not rth.empty else pm
    if bars.empty or prev_close <= 0:
        return None
    price = float(bars["Close"].dropna().iloc[-1])
    gap = (price / prev_close - 1) * 100
    pm_vol = int(pm["Volume"].fillna(0).sum()) if not pm.empty else 0
    if gap <= C.MIN_GAP_PCT or price <= C.MIN_PRICE or pm_vol <= C.MIN_PREMARKET_VOLUME:
        return None
    return {
        "ticker": ticker,
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "gap_pct": round(gap, 2),
        "premarket_volume": pm_vol,
        "premarket_high": round(float(pm["High"].max()), 2) if not pm.empty else None,
    }


def scan(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(C.ET)
    today = now.date()
    universe = load_universe()
    log.info("Universe: %d tickers", len(universe))
    daily = md.daily_bars(universe, period="5d")
    intra = md.intraday_bars(list(daily))
    hits = []
    for t in intra:
        try:
            h = evaluate(t, daily[t], intra[t], today)
        except Exception as e:
            log.debug("skip %s: %s", t, e)
            continue
        if h:
            hits.append(h)
    hits.sort(key=lambda h: h["gap_pct"], reverse=True)
    hits = hits[: C.MAX_RESULTS]
    for h in hits:
        h["catalyst"], h["catalyst_source"] = get_catalyst(h["ticker"])
    save(hits, now)
    return hits


# ---------- persistence ----------
def results_path(d):
    return C.RESULTS_DIR / f"premarket_{d.isoformat()}.json"


def save(hits, now):
    C.RESULTS_DIR.mkdir(exist_ok=True)
    p = results_path(now.date())
    data = json.loads(p.read_text()) if p.exists() else {"date": now.date().isoformat(), "runs": []}
    data["runs"].append({"run_at": now.isoformat(timespec="seconds"), "hits": hits})
    data["latest"] = data["runs"][-1]
    seen = dict.fromkeys(data.get("all_tickers", []))
    seen.update(dict.fromkeys(h["ticker"] for h in hits))
    data["all_tickers"] = list(seen)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    log.info("Saved %d hits -> %s", len(hits), p)


def load_today(d):
    p = results_path(d)
    return json.loads(p.read_text()) if p.exists() else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for h in scan():
        print(f"{h['ticker']:6} ${h['price']:<9} +{h['gap_pct']:.1f}%  vol {h['premarket_volume']:,}  {h['catalyst']}")
