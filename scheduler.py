"""Runs both scanners on a weekday schedule (US Eastern time) and sends to LINE/Discord.

  Scanner A: 08:30, 09:00 ... 14:00 ET (every 30 min)
  Scanner B: 5 min after each A run (08:35 ... 14:35) + final run 15:00 ET,
             using Scanner A's tickers. Before 10:00 it reports "not active yet".
  One message after each B run contains both sections (+ portfolio price alerts if any).
  Portfolio summary: daily at PORTFOLIO_SUMMARY_TIME (16:10 ET).
  results/dashboard.html is rebuilt after every run.

    python scheduler.py          # run forever
    python scheduler.py --once   # run A then B right now and send (for testing)
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config as C
import dashboard
import market_context as mc
import notify
import portfolio
import premarket_scanner as A
import strategy_scanner as B

log = logging.getLogger("scheduler")


def _in(now, start, end):
    return start <= now.time().replace(second=0, microsecond=0) <= end


def run_a(force=False):
    now = datetime.now(C.ET)
    if not force and (not C.is_trading_day(now.date()) or not _in(now, C.PREMARKET_FIRST, C.PREMARKET_LAST)):
        return
    try:
        hits = A.scan(now)
        log.info("Scanner A: %d hits", len(hits))
    except Exception:
        log.exception("Scanner A crashed")


def run_b(force=False):
    now = datetime.now(C.ET)
    if not force and not C.is_trading_day(now.date()):
        return
    try:
        b = B.scan(now, force=force)
    except Exception:
        log.exception("Scanner B crashed")
        b = {"status": "ok", "hits": [], "checked": 0}
    data = A.load_today(now.date())
    a_hits = data["latest"]["hits"] if data else []
    alerts, snap = [], None
    try:
        snap = portfolio.snapshot(now)
        alerts = portfolio.new_alerts(snap, now)
    except Exception:
        log.exception("Portfolio check crashed")
    ctx = build_context(now, a_hits, b, snap, data)
    msg = notify.format_message(a_hits, b, now, alerts, ctx)
    if force:
        notify.send(msg, priority=True)
    else:
        notify.send_if_changed(msg, now, priority=bool(alerts))
    _refresh_dashboard()
    log.info("Scanner B: %s, %d hits, %d new alerts", b["status"], len(b["hits"]), len(alerts))


def build_context(now, a_hits, b, snap, a_data):
    """Market regime, earnings flags, position sizes and data coverage for the message."""
    ctx = {}
    try:
        reg = (snap or {}).get("market") or mc.regime()
        ctx["regime_line"] = mc.regime_line(reg)
        tickers = list(dict.fromkeys([h["ticker"] for h in a_hits] + [h["ticker"] for h in b["hits"]]))
        ed = mc.next_earnings(tickers, now.date()) if tickers else {}
        ctx["earnings_days"] = {t: n for t, d in ed.items()
                                if (n := mc.earnings_soon(d, now.date())) is not None}
        ctx["sizing"] = {h["ticker"]: sz for h in b["hits"]
                         if (sz := mc.position_size(h["price"], h["stop_ref"]))}
        if a_data and a_data.get("latest"):
            ctx["coverage_pct"] = a_data["latest"].get("coverage_pct")
    except Exception:
        log.exception("Context build failed")
    return ctx


def _refresh_dashboard():
    try:
        dashboard.write()
    except Exception:
        log.exception("Dashboard build failed")


def run_summary(force=False):
    """Daily portfolio summary after the close."""
    now = datetime.now(C.ET)
    if not force and not C.is_trading_day(now.date()):
        return
    try:
        snap = portfolio.snapshot(now)
        notify.send(portfolio.format_summary(snap, now), priority=True)
    except Exception:
        log.exception("Portfolio summary crashed")
    _refresh_dashboard()


def main():
    sched = BlockingScheduler(timezone=C.ET)
    days = "mon-fri"
    # A: :00/:30 from 08:30 to 14:00 (window enforced in run_a)
    sched.add_job(run_a, CronTrigger(day_of_week=days, hour="8-14", minute="0,30", timezone=C.ET),
                  id="scanner_a", misfire_grace_time=300, max_instances=1)
    # B: :05/:35 from 08:35 to 14:35, plus 15:00
    sched.add_job(_guarded_b, CronTrigger(day_of_week=days, hour="8-14", minute="5,35", timezone=C.ET),
                  id="scanner_b", misfire_grace_time=300, max_instances=1)
    sched.add_job(run_b, CronTrigger(day_of_week=days, hour=15, minute=0, timezone=C.ET),
                  id="scanner_b_final", misfire_grace_time=300)
    st = C.PORTFOLIO_SUMMARY_TIME
    sched.add_job(run_summary, CronTrigger(day_of_week=days, hour=st.hour, minute=st.minute, timezone=C.ET),
                  id="portfolio_summary", misfire_grace_time=1800)
    log.info("Scheduler started (ET). Ctrl+C to stop.")
    sched.start()


def _guarded_b():
    """B window: 08:35-14:35 and 15:00."""
    now = datetime.now(C.ET)
    if _in(now, C.PREMARKET_FIRST.replace(minute=35), C.STRATEGY_LAST):
        run_b()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if "--once" in sys.argv:
        run_a(force=True)
        run_b(force=True)
        run_summary(force=True)
    else:
        main()
