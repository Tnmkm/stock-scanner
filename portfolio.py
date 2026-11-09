"""Portfolio tracker: P/L, technical levels, news and price alerts for holdings in portfolio.csv.

portfolio.csv columns (one row per stock):
    ticker, shares, avg_cost, stop, target, note
  - stop   : alert when price <= stop. Blank = avg_cost minus DEFAULT_STOP_PCT
  - target : alert when price >= target. Blank = no target alert

    python portfolio.py            # print snapshot + alerts (sends nothing)
    python portfolio.py --send     # also send the daily summary now
"""
from __future__ import annotations

import csv
import json
import logging
import sys
from datetime import datetime

import pandas as pd

import config as C
import market_data as md
from premarket_scanner import get_catalyst

log = logging.getLogger("portfolio")
PORTFOLIO_FILE = C.BASE_DIR / "portfolio.csv"


# ---------- load ----------
def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def load_portfolio() -> list[dict]:
    if not PORTFOLIO_FILE.exists():
        return []
    rows = []
    with PORTFOLIO_FILE.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = (r.get("ticker") or "").strip().upper()
            if not t or t.startswith("#"):
                continue
            cost = _num(r.get("avg_cost"))
            stop = _num(r.get("stop"))
            if stop is None and cost:
                stop = round(cost * (1 - C.DEFAULT_STOP_PCT / 100), 2)
            rows.append({"ticker": t, "shares": _num(r.get("shares")) or 0.0,
                         "avg_cost": cost, "stop": stop, "target": _num(r.get("target")),
                         "note": (r.get("note") or "").strip()})
    return rows


# ---------- indicators (pure) ----------
def rsi(close: pd.Series, n=14) -> float | None:
    d = close.diff().dropna()
    if len(d) < n:
        return None
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    last_dn = dn.iloc[-1]
    if last_dn == 0:
        return 100.0
    return round(float(100 - 100 / (1 + up.iloc[-1] / last_dn)), 1)


def analyze(holding: dict, daily: pd.DataFrame, today) -> dict:
    """Snapshot for one holding from daily bars (today's partial bar included if present)."""
    d = daily.dropna(subset=["Close"])
    dates = [ts.date() for ts in d.index]
    price = float(d["Close"].iloc[-1])
    prev = float(d["Close"].iloc[-2]) if len(d) > 1 else price
    hist = d.iloc[:-1] if dates[-1] == today else d          # completed sessions only
    close = d["Close"]

    def sma(n):
        return round(float(close.rolling(n).mean().iloc[-1]), 2) if len(close) >= n else None

    shares, cost = holding["shares"], holding["avg_cost"]
    value = price * shares
    out = {
        **holding,
        "price": round(price, 2),
        "live": dates[-1] == today,          # False before today's session has data
        "day_change_pct": round((price / prev - 1) * 100, 2) if prev else 0.0,
        "value": round(value, 2),
        "sma20": sma(20), "sma50": sma(50), "sma200": sma(200),
        "rsi14": rsi(close),
        "support_20d": round(float(hist["Low"].tail(20).min()), 2) if len(hist) else None,
        "resistance_20d": round(float(hist["High"].tail(20).max()), 2) if len(hist) else None,
        "history": [[ts.strftime("%Y-%m-%d"), round(float(c), 2)]
                    for ts, c in close.tail(90).items()],
    }
    if cost:
        out["pl"] = round((price - cost) * shares, 2)
        out["pl_pct"] = round((price / cost - 1) * 100, 2)
    else:
        out["pl"] = out["pl_pct"] = None
    out["trend"] = ("up" if out["sma50"] and out["sma200"] and price > out["sma50"] > out["sma200"]
                    else "down" if out["sma50"] and out["sma200"] and price < out["sma50"] < out["sma200"]
                    else "mixed")
    return out


def check_alerts(s: dict) -> list[dict]:
    """Price-level alerts for one snapshot."""
    a = []
    if s.get("stop") and s["price"] <= s["stop"]:
        a.append({"ticker": s["ticker"], "kind": "stop",
                  "text": f"🔻 {s['ticker']} ${s['price']} หลุดจุดตัดขาดทุน ${s['stop']}"})
    if s.get("target") and s["price"] >= s["target"]:
        a.append({"ticker": s["ticker"], "kind": "target",
                  "text": f"🎯 {s['ticker']} ${s['price']} ถึงเป้า ${s['target']}"})
    if s.get("live", True) and abs(s["day_change_pct"]) >= C.BIG_MOVE_PCT:
        arrow = "🚀" if s["day_change_pct"] > 0 else "⚠️"
        a.append({"ticker": s["ticker"], "kind": "move_up" if s["day_change_pct"] > 0 else "move_down",
                  "text": f"{arrow} {s['ticker']} เคลื่อนไหวแรง {s['day_change_pct']:+.1f}% วันนี้ (${s['price']})"})
    return a


# ---------- run ----------
def snapshot(now: datetime | None = None, with_news=True) -> dict:
    now = now or datetime.now(C.ET)
    holdings = load_portfolio()
    if not holdings:
        return {"as_of": now.isoformat(timespec="seconds"), "holdings": [], "totals": {}}
    daily = md.daily_bars([h["ticker"] for h in holdings], period="1y")
    rows = []
    for h in holdings:
        if h["ticker"] not in daily:
            log.warning("no data for %s", h["ticker"])
            continue
        s = analyze(h, daily[h["ticker"]], now.date())
        if with_news:
            s["news"], s["news_source"] = get_catalyst(h["ticker"])
        rows.append(s)
    total_value = sum(r["value"] for r in rows)
    costed = [r for r in rows if r["avg_cost"]]
    total_cost = sum(r["avg_cost"] * r["shares"] for r in costed)
    day_pl = sum(r["value"] - r["value"] / (1 + r["day_change_pct"] / 100) for r in rows)
    for r in rows:
        r["weight_pct"] = round(r["value"] / total_value * 100, 1) if total_value else 0
    totals = {
        "value": round(total_value, 2),
        "cost": round(total_cost, 2),
        "pl": round(sum(r["pl"] for r in costed), 2) if total_cost else None,
        "pl_pct": round((sum(r["value"] for r in costed) / total_cost - 1) * 100, 2) if total_cost else None,
        "day_pl": round(day_pl, 2),
    }
    snap = {"as_of": now.isoformat(timespec="seconds"), "holdings": rows, "totals": totals}
    C.RESULTS_DIR.mkdir(exist_ok=True)
    (C.RESULTS_DIR / "portfolio_latest.json").write_text(json.dumps(snap, indent=2, ensure_ascii=False))
    return snap


def new_alerts(snap: dict, now: datetime) -> list[dict]:
    """Alerts not yet sent today (each ticker+kind fires once per day)."""
    p = C.RESULTS_DIR / f"alerts_{now.date().isoformat()}.json"
    sent = set(json.loads(p.read_text())) if p.exists() else set()
    fresh = []
    for s in snap["holdings"]:
        for a in check_alerts(s):
            key = f"{a['ticker']}:{a['kind']}"
            if key not in sent:
                fresh.append(a)
                sent.add(key)
    C.RESULTS_DIR.mkdir(exist_ok=True)
    p.write_text(json.dumps(sorted(sent)))
    return fresh


def format_summary(snap: dict, now: datetime) -> str:
    t = snap["totals"]
    lines = [f"[Portfolio Summary] {now.strftime('%d %b %Y')}"]
    if not snap["holdings"]:
        return lines[0] + "\nportfolio.csv is empty."
    pl = (f" | P/L {t['pl']:+,.2f} ({t['pl_pct']:+.1f}%)"
          if t.get("pl") is not None and t.get("pl_pct") is not None else "")
    day = 0.0 if abs(t["day_pl"]) < 0.005 else t["day_pl"]
    lines.append(f"มูลค่า ${t['value']:,.2f} | วันนี้ {day:+,.2f}{pl}")
    lines.append("")
    for s in sorted(snap["holdings"], key=lambda r: -r["value"]):
        pl = f" | P/L {s['pl_pct']:+.1f}%" if s.get("pl_pct") is not None else ""
        trend = {"up": "📈", "down": "📉", "mixed": "↔️"}[s["trend"]]
        lines.append(f"{trend} {s['ticker']} ${s['price']} ({s['day_change_pct']:+.1f}%){pl}")
        lvl = []
        if s.get("support_20d"):
            lvl.append(f"รับ {s['support_20d']}")
        if s.get("resistance_20d"):
            lvl.append(f"ต้าน {s['resistance_20d']}")
        if s.get("rsi14") is not None:
            lvl.append(f"RSI {s['rsi14']}")
        if s.get("stop"):
            lvl.append(f"SL {s['stop']}")
        lines.append("   " + " | ".join(lvl))
        if s.get("news"):
            lines.append(f"   📰 {s['news']}")
    lines += ["", "ข้อมูลเพื่อการศึกษา ไม่ใช่คำแนะนำซื้อขาย"]
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    now = datetime.now(C.ET)
    snap = snapshot(now)
    text = format_summary(snap, now)
    print(text)
    alerts = [a for s in snap["holdings"] for a in check_alerts(s)]
    if alerts:
        print("\nAlerts now:\n" + "\n".join(a["text"] for a in alerts))
    if "--send" in sys.argv:
        import notify
        print("sent" if notify.send(text) else "failed")
