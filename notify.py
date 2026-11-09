"""Format both scanners' results and send them to every configured channel
(LINE Messaging API and/or Discord webhook - whichever has values in .env).

    python notify.py --test     # send a test message
"""
from __future__ import annotations
import hashlib
import logging
import sys

import requests

import config as C

log = logging.getLogger("notify")
TEXT_LIMIT = 1900  # Discord max is 2000 chars per message


def _earn_tag(ticker, ctx):
    n = (ctx or {}).get("earnings_days", {}).get(ticker)
    return f" 📅 งบใน {n} วัน" if n is not None else ""


def format_message(a_hits, b_result, now, alerts=None, ctx=None) -> str:
    """ctx (optional): {'regime_line': str, 'earnings_days': {ticker: days},
                        'sizing': {ticker: {...}}, 'coverage_pct': int}"""
    ctx = ctx or {}
    lines = ["[Scanner A: Pre-market Gappers]"]
    if a_hits:
        for i, h in enumerate(a_hits, 1):
            lines.append(f"{i}. {h['ticker']} | ${h['price']:.2f} | +{h['gap_pct']:.1f}%{_earn_tag(h['ticker'], ctx)}")
            lines.append(f"   📰 {h['catalyst']}")
    else:
        lines.append("No stocks met the criteria.")

    lines += ["", "[Scanner B: Trend-join Long Hits]"]
    status = b_result.get("status")
    if status == "waiting":
        lines.append("Not active yet — starts after 10:00 AM ET.")
    elif status == "no_input":
        lines.append("No tickers from Scanner A to check.")
    elif not b_result["hits"]:
        lines.append(f"No valid entry ({b_result['checked']} checked).")
    else:
        for i, h in enumerate(b_result["hits"], 1):
            lines.append(f"{i}. {h['ticker']} ✅ Entry ~${h['price']:.2f}{_earn_tag(h['ticker'], ctx)}")
            lines.append(f"   > Y-High ${h['yesterday_high']} | PM-High ${h['premarket_high']}"
                         f" | HOD ${h['hod_before_bar']} | 200SMA ${h['sma200']}")
            lines.append(f"   Stop ref ${h['stop_ref']} (-{h['risk_pct']}%)")
            sz = ctx.get("sizing", {}).get(h["ticker"])
            if sz:
                lines.append(f"   Size {sz['shares']} หุ้น (~${sz['cost_usd']:,.0f}, เสี่ยง ${sz['risk_usd']:,.0f})")
    if alerts:
        lines += ["", "[Price Alerts: My Portfolio]"] + [a["text"] for a in alerts]
    if ctx.get("coverage_pct") is not None and ctx["coverage_pct"] < C.LOW_DATA_PCT:
        lines += ["", f"⚠️ ดึงข้อมูลได้แค่ {ctx['coverage_pct']}% ของหุ้นที่สแกน ผลอาจไม่ครบ"]
    if ctx.get("regime_line"):
        lines += ["", ctx["regime_line"]]
    lines += ["", f"⏱ {now.strftime('%H:%M')} ET"]
    return "\n".join(lines)


def _chunks(text, limit=TEXT_LIMIT):
    while text:
        if len(text) <= limit:
            yield text
            return
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > 0 else limit
        yield text[:cut]
        text = text[cut:].lstrip("\n")


def _send_discord(text) -> bool:
    ok = True
    for chunk in _chunks(text, 1900):
        r = requests.post(C.DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=15)
        if r.status_code not in (200, 204):
            log.error("Discord post failed %s: %s", r.status_code, r.text[:300])
            ok = False
    return ok


def _send_line(text) -> bool:
    # one push (up to 5 bubbles) to one user = 1 message of the monthly quota
    msgs = [{"type": "text", "text": c} for c in list(_chunks(text, 4900))[:5]]
    r = requests.post("https://api.line.me/v2/bot/message/push",
                      headers={"Authorization": f"Bearer {C.LINE_CHANNEL_ACCESS_TOKEN}"},
                      json={"to": C.LINE_USER_ID, "messages": msgs}, timeout=15)
    if r.status_code != 200:
        log.error("LINE push failed %s: %s", r.status_code, r.text[:300])
        return False
    return True


def line_quota_left() -> int | None:
    """Pushes left this month on the LINE plan (None if unknown)."""
    h = {"Authorization": f"Bearer {C.LINE_CHANNEL_ACCESS_TOKEN}"}
    try:
        q = requests.get("https://api.line.me/v2/bot/message/quota", headers=h, timeout=10).json()
        used = requests.get("https://api.line.me/v2/bot/message/quota/consumption",
                            headers=h, timeout=10).json().get("totalUsage", 0)
        if q.get("type") == "limited":
            return int(q.get("value", 0)) - int(used)
    except Exception as e:
        log.warning("LINE quota check failed: %s", e)
    return None


def send(text: str, priority: bool = False) -> bool:
    """Send to every configured channel. True if at least one succeeded.
    Non-priority LINE messages are skipped when the monthly quota is nearly used up."""
    results = []
    if C.LINE_CHANNEL_ACCESS_TOKEN and C.LINE_USER_ID:
        left = None if priority else line_quota_left()
        if left is not None and left <= C.LINE_QUOTA_RESERVE:
            log.warning("LINE quota low (%s left) - routine message not sent to LINE", left)
        else:
            results.append(_send_line(text))
    if C.DISCORD_WEBHOOK_URL:
        results.append(_send_discord(text))
    if not results:
        if not (C.LINE_CHANNEL_ACCESS_TOKEN or C.DISCORD_WEBHOOK_URL):
            log.error("No channel configured: fill LINE_* or DISCORD_WEBHOOK_URL in .env")
        print(text)
        return False
    return any(results)


def send_if_changed(text: str, now, priority: bool = False) -> bool:
    """Optionally skip content identical to the last message (ignoring the time line)."""
    body = text.rsplit("\n⏱", 1)[0]
    digest = hashlib.sha1(body.encode()).hexdigest()
    marker = C.RESULTS_DIR / f".last_sent_{now.date().isoformat()}"
    if not priority and C.SKIP_UNCHANGED and marker.exists() and marker.read_text() == digest:
        log.info("Unchanged since last send — skipped")
        return False
    ok = send(text, priority=priority)
    if ok:
        C.RESULTS_DIR.mkdir(exist_ok=True)
        marker.write_text(digest)
    return ok


if __name__ == "__main__" and "--test" in sys.argv:
    logging.basicConfig(level=logging.INFO)
    print("sent" if send("✅ Stock scanner connected") else "failed")
