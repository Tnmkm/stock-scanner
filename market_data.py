"""Thin wrappers around yfinance shared by both scanners."""
from __future__ import annotations
import logging
from datetime import date, time as dtime

import pandas as pd
import yfinance as yf

from config import BASE_DIR, ET

log = logging.getLogger(__name__)
CHUNK = 40      # tickers per request batch
THREADS = 4     # parallel connections; macOS allows only 256 open files by default

# Raise the open-file limit (macOS default 256 is too low for batch downloads)
try:
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = 4096 if hard == resource.RLIM_INFINITY else min(4096, hard)
    if soft < target:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
except Exception:
    pass

# Keep yfinance's cache inside the project folder
try:
    _cache = BASE_DIR / ".yf_cache"
    _cache.mkdir(exist_ok=True)
    yf.set_tz_cache_location(str(_cache))
except Exception:
    pass

logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # we report failures ourselves


def _slice(df: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Pull one ticker's OHLCV out of a (possibly multi-ticker) yf.download frame."""
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = df.columns.get_level_values(0)
        if ticker in lvl0:
            sub = df[ticker]
        elif ticker in df.columns.get_level_values(1):
            sub = df.xs(ticker, axis=1, level=1)
        else:
            return None
    else:
        sub = df
    sub = sub.dropna(how="all")
    return sub if not sub.empty else None


def _download_once(tickers, **kwargs):
    out = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        try:
            df = yf.download(chunk, group_by="ticker", auto_adjust=False,
                             progress=False, threads=THREADS, **kwargs)
        except Exception as e:  # network hiccup: skip chunk, keep going
            log.warning("download failed for %s..: %s", chunk[:3], e)
            continue
        for t in chunk:
            sub = _slice(df, t)
            if sub is not None:
                out[t] = sub
    return out


def download(tickers: list[str], **kwargs) -> dict[str, pd.DataFrame]:
    """Batch download with one retry for tickers that came back empty."""
    out = _download_once(tickers, **kwargs)
    missing = [t for t in tickers if t not in out]
    if missing:
        out.update(_download_once(missing, **kwargs))
        missing = [t for t in tickers if t not in out]
    log.info("Downloaded %d/%d tickers (%s)", len(out), len(tickers),
             kwargs.get("interval", ""))
    if missing and len(missing) > len(tickers) * 0.5:
        log.warning("Over half the tickers failed - check internet connection")
    return out


def daily_bars(tickers, period="5d"):
    return download(tickers, period=period, interval="1d")


def intraday_bars(tickers):
    """Today's 1-minute bars including pre-market (prepost=True)."""
    return download(tickers, period="1d", interval="1m", prepost=True)


def to_et(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    idx = df.index
    df.index = idx.tz_localize("UTC").tz_convert(ET) if idx.tz is None else idx.tz_convert(ET)
    return df


def split_sessions(intra: pd.DataFrame, today: date):
    """-> (premarket bars, regular-session bars) for `today`, ET."""
    intra = to_et(intra)
    intra = intra[intra.index.date == today]
    t = intra.index.time
    pm = intra[(t >= dtime(4, 0)) & (t < dtime(9, 30))]
    rth = intra[(t >= dtime(9, 30)) & (t < dtime(16, 0))]
    return pm, rth


def before_today(daily: pd.DataFrame, today: date) -> pd.DataFrame:
    """Daily bars strictly before `today` (drops today's partial bar)."""
    d = daily.copy()
    dates = pd.Index([ts.date() for ts in d.index])
    return d[dates < today].dropna(subset=["Close"])
