"""Shared settings for the pre-market + Trend-join Long scanners."""
from __future__ import annotations
import os
from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

ET = ZoneInfo("America/New_York")
BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
UNIVERSE_FILE = BASE_DIR / "universe.txt"

# ---- Scanner A: pre-market gappers ----
MIN_GAP_PCT = 5.0            # % above previous close
MIN_PRICE = 3.0              # USD
MIN_PREMARKET_VOLUME = 50_000
# Yahoo predefined screens merged into the scan universe (plus universe.txt)
YAHOO_SCREENS = ["day_gainers", "most_actives", "small_cap_gainers", "aggressive_small_caps"]
SCREEN_COUNT = 100
MAX_RESULTS = 25             # cap hits shown/sent per run

# ---- Scanner B: Trend-join Long ----
STRATEGY_START = time(10, 0)  # criteria only valid after 10:00 ET
SMA_LENGTH = 200
# "union"  = every ticker that hit Scanner A at any run today
# "latest" = only tickers from the most recent Scanner A run
STRATEGY_TICKER_SOURCE = "union"

# ---- Portfolio (portfolio.csv) ----
DEFAULT_STOP_PCT = 10.0       # stop alert at avg_cost -10% when no stop is set
BIG_MOVE_PCT = 5.0            # alert when a holding moves this much in a day
PORTFOLIO_SUMMARY_TIME = time(16, 10)   # daily summary after the close (ET) = ~04:10 Thai time
# LINE free plan = 300 pushes/month. Below this many left, only alerts + daily summary are sent.
LINE_QUOTA_RESERVE = 40

# ---- Risk & context ----
# Account size for position sizing on Scanner B hits (0 = sizing off). Can also come from env.
ACCOUNT_SIZE_USD = float(os.getenv("ACCOUNT_SIZE_USD", "0") or 0)
RISK_PER_TRADE_PCT = 2.0      # max loss per trade if the stop is hit (% of account)
MAX_POSITION_PCT = 25.0       # never put more than this % of the account in one stock
EARNINGS_WARN_DAYS = 7        # flag stocks reporting earnings within this many days
LOW_DATA_PCT = 50             # warn when fewer than this % of tickers downloaded

# ---- Schedule (ET, weekdays) ----
PREMARKET_FIRST = time(8, 30)
PREMARKET_LAST = time(14, 0)
STRATEGY_OFFSET_MIN = 5
STRATEGY_LAST = time(15, 0)

# ---- Keys (put them in .env) ----
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")
# True = skip sending when results are identical to the last message sent today
SKIP_UNCHANGED = True
BENZINGA_API_KEY = os.getenv("BENZINGA_API_KEY", "")

# Full-day NYSE closures (early-close days still run)
NYSE_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS
