"""One-shot entry point for running in the cloud (GitHub Actions).

GitHub's scheduler fires every 30 min (and can be late), so this script decides
what is due from the current US Eastern time:
  08:25-15:10 ET  -> Scanner A (until ~14:05) then Scanner B + portfolio alerts, send
  >= 16:00 ET     -> daily portfolio summary (once per day)
Results in results/ are persisted between runs by the workflow.

    python cloud_run.py                 # do whatever is due now
    python cloud_run.py --force scan    # run scan now regardless of time
    python cloud_run.py --force summary # send summary now
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, time, timedelta

import config as C


def _write_portfolio_from_env():
    """Holdings live in the PORTFOLIO_CSV secret so they never sit in the repo."""
    csv_text = os.getenv("PORTFOLIO_CSV", "").strip()
    if csv_text:
        (C.BASE_DIR / "portfolio.csv").write_text(csv_text + "\n", encoding="utf-8")


def _prune_old_results(keep_days=14):
    cutoff = datetime.now(C.ET).date() - timedelta(days=keep_days)
    for p in C.RESULTS_DIR.glob("*_20*.json"):
        try:
            d = datetime.strptime(p.stem.rsplit("_", 1)[-1], "%Y-%m-%d").date()
            if d < cutoff:
                p.unlink()
        except ValueError:
            pass


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    log = logging.getLogger("cloud")
    _write_portfolio_from_env()
    C.RESULTS_DIR.mkdir(exist_ok=True)

    import dashboard
    import premarket_scanner as A
    import scheduler as S

    now = datetime.now(C.ET)
    t = now.time()
    forced = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--force" else None
    log.info("ET now %s, forced=%s", now.strftime("%a %H:%M"), forced)

    if forced in ("scan", "all"):
        A.scan(now)
        S.run_b(force=True)
    if forced in ("summary", "all"):
        S.run_summary(force=True)
    if forced:
        dashboard.write()
        return

    if not C.is_trading_day(now.date()):
        log.info("Market closed today - nothing to do")
        return

    did = False
    if time(8, 25) <= t <= time(15, 10):
        if t <= time(14, 5):
            A.scan(now)
        S.run_b()
        did = True

    marker = C.RESULTS_DIR / f".summary_{now.date().isoformat()}"
    if t >= time(16, 0) and not marker.exists():
        S.run_summary()
        marker.write_text("sent")
        did = True

    if not did:
        log.info("Nothing scheduled at this time")
    dashboard.write()
    _prune_old_results()


if __name__ == "__main__":
    main()
