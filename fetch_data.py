"""
Nasdaq-100 Investment Scoring System - Data Fetcher & Scoring Engine
=====================================================================
Pulls ~20 years of NDX (^NDX) and VIX (^VIX) daily data from Yahoo Finance,
computes MA200, 5-year valuation percentile, deviation, and applies the
3-dimension scoring model (PE / MA200 / VIX) to produce a 0-100 composite
score with letter grade. Early rows where indicators lack lookback history are
kept (price/VIX/PE only) so the long-run trend chart spans the full window.

Outputs:
    ndx_history.json  - Full ~20y daily series with scores
    ndx_snapshot.json - Latest snapshot only
    index.html        - Self-contained dashboard (data inlined from template.html)

Usage:
    python fetch_data.py
"""

from __future__ import annotations

import json
import sys
import math
import html
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

import numpy as np
import pandas as pd
import yfinance as yf


# ============================================================================
# 1. Data Fetching
# ============================================================================

def fetch_market_data(start: str = None, end: str = None) -> pd.DataFrame:
    """Fetch NDX close + VIX close for the given window.

    Both bounds default dynamically: `end` is ~5 days ahead of today (so the
    latest session is included — yfinance's `end` is exclusive), and `start`
    is ~20 years back so the long-run trend chart spans two decades of history.
    """
    if end is None:
        end = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    if start is None:
        start = (datetime.now() - timedelta(days=20 * 365)).strftime("%Y-%m-%d")
    print(f"Fetching NDX (^NDX) and VIX (^VIX) from {start} to {end}...")

    # Auto-adjust end to today if needed
    ndx = yf.download("^NDX", start=start, end=end, progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=True)

    if ndx.empty or vix.empty:
        raise RuntimeError(
            "Failed to fetch data. Check network / proxy. "
            "If behind GFW, configure SOCKS5 proxy or use a mirror source."
        )

    # Flatten MultiIndex columns if present
    if isinstance(ndx.columns, pd.MultiIndex):
        ndx.columns = ndx.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    df = pd.DataFrame({
        "ndx": ndx["Close"].squeeze(),
        "vix": vix["Close"].squeeze(),
    })
    df = df.dropna()

    print(f"  -> {len(df)} trading days loaded ({df.index[0].date()} to {df.index[-1].date()})")
    return df


# ============================================================================
# 2. Indicator Computation
# ============================================================================

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA200, deviation, valuation-percentile, and PE-style metric."""
    out = df.copy()

    # 200-day moving average
    out["ma200"] = out["ndx"].rolling(window=200, min_periods=50).mean()

    # Deviation from MA200 (percent)
    out["dev_pct"] = (out["ndx"] / out["ma200"] - 1.0) * 100.0

    # 5-year valuation percentile: rolling rank of NDX close within last ~1260 sessions.
    # 10y percentile gets pinned near 99% in a long bull run; 5y keeps the signal alive.
    WINDOW = 1260

    def rolling_pct(s: pd.Series) -> pd.Series:
        # Rank of last value in the trailing window, as a percentile in [0, 100]
        ranks = s.rolling(window=WINDOW, min_periods=WINDOW // 2).rank(pct=True)
        return ranks * 100.0

    out["val_pct"] = rolling_pct(out["ndx"])

    # PE proxy from 5y valuation percentile, calibrated so that around middle
    # of the 5y range the implied PE is ~28-32 (matches Nasdaq-100 reality).
    base_pe = 27.5
    pe_amp = 6.0
    out["pe"] = base_pe + (out["val_pct"] - 50.0) / 50.0 * pe_amp
    out["pe_pct"] = out["val_pct"].round(1)

    # Smooth VIX (some days have nulls in yfinance)
    out["vix"] = out["vix"].ffill().bfill()

    # NOTE: do not drop rows missing ma200/val_pct. The long-run trend chart
    # needs the full ~20y price history even where scoring indicators aren't
    # computable yet (they ramp in after their lookback windows).
    return out


# ============================================================================
# 3. Scoring Engine
# ============================================================================

def score_pe(pe_percentile: float) -> float:
    """PE percentile -> 0..30. Lower percentile => higher score (cheaper)."""
    if pd.isna(pe_percentile):
        return 0.0
    return max(0.0, 30.0 * (1.0 - pe_percentile / 100.0))


def score_ma(dev_pct: float) -> float:
    """MA200 deviation (%) -> 0..40. Larger positive deviation => lower score.
    Non-linear: anything above +12% saturates at 0; negative deviation rewards."""
    if pd.isna(dev_pct):
        return 0.0
    if dev_pct >= 12.0:
        return 0.0
    if dev_pct <= -20.0:
        return 40.0
    # Non-linear curve: 40 * (1 - max(0, dev) / 15)^1.5  with floor for negative deviations
    pos = max(0.0, dev_pct)
    s = 40.0 * (1.0 - pos / 15.0) ** 1.5
    if dev_pct < 0:
        s += min(40.0 - s, abs(dev_pct) * 1.0)
    return float(np.clip(s, 0.0, 40.0))


def score_vix(vix: float) -> float:
    """VIX -> 0..30. Higher VIX => higher score (more fear = buy opportunity)."""
    if pd.isna(vix):
        return 0.0
    raw = (vix - 14.0) * 1.7
    return float(np.clip(raw, 0.0, 30.0))


def total_grade(score: float) -> str:
    """Composite score -> letter grade."""
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "E"


def grade_color(grade: str) -> str:
    return {
        "A": "#16a34a",  # green
        "B": "#65a30d",  # lime
        "C": "#ca8a04",  # amber
        "D": "#ea580c",  # orange
        "E": "#dc2626",  # red
    }.get(grade, "#6b7280")


def grade_label(grade: str) -> str:
    return {
        "A": "极度低估，加大买入",
        "B": "低估，可分批加仓",
        "C": "合理估值，正常持有",
        "D": "偏高，正常定投",
        "E": "严重高估，减仓观望",
    }.get(grade, "—")


def grade_strategy(grade: str) -> str:
    return {
        "A": "重仓买入",
        "B": "加大投入",
        "C": "维持定投",
        "D": "正常定投",
        "E": "暂停或减仓",
    }.get(grade, "—")


# ============================================================================
# 4b. Helper: download ECharts library locally
# ============================================================================

ECHARTS_URLS = [
    "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js",
    "https://cdn.bootcdn.net/ajax/libs/echarts/5.4.3/echarts.min.js",
    "https://unpkg.com/echarts@5.4.3/dist/echarts.min.js",
]


def _download_echarts(out_path: Path) -> None:
    """Download the ECharts library using urllib (no extra deps) from a
    fallback list of CDNs. Saves to out_path. Raises if all fail."""
    import urllib.request, urllib.error, ssl

    ctx = ssl.create_default_context()
    last_err = None
    for url in ECHARTS_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = resp.read()
            out_path.write_bytes(data)
            print(f"  -> {url} -> {len(data)} bytes -> {out_path.name}")
            return
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            print(f"  [skip] {url} ({e})")
            last_err = e
    raise RuntimeError(f"Failed to download echarts: {last_err}")


def apply_scoring(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised scoring across the whole frame.

    Components that depend on a lookback window — PE needs the 5y valuation
    percentile, MA needs the 200-day average — are left as None until enough
    history exists, so the composite score only appears where it is fully
    meaningful. VIX scoring is available across the whole history.
    """
    out = df.copy()
    out["pe_score"] = out["pe_pct"].apply(lambda v: None if pd.isna(v) else round(score_pe(v), 1))
    out["ma_score"] = out["dev_pct"].apply(lambda v: None if pd.isna(v) else round(score_ma(v), 1))
    out["vix_score"] = out["vix"].apply(lambda v: None if pd.isna(v) else round(score_vix(v), 1))

    def _total(row):
        ps, ms, vs = row["pe_score"], row["ma_score"], row["vix_score"]
        if pd.isna(ps) or pd.isna(ms) or pd.isna(vs):
            return None
        return round(float(ps) + float(ms) + float(vs), 1)

    out["total"] = out.apply(_total, axis=1)
    out["grade"] = out["total"].apply(lambda t: None if pd.isna(t) else total_grade(t))
    return out


# ============================================================================
# 4. JSON Serialisation
# ============================================================================

def _num(v, d=1):
    """Return a rounded float, or None for NaN/None so the emitted JSON stays valid."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return round(f, d)


def to_records(df: pd.DataFrame) -> List[Dict]:
    """Convert DataFrame to a list of dicts with stringified dates.

    Numeric fields are None where the underlying indicator isn't computable
    yet (early history); this keeps the emitted JSON valid (no NaN literals).
    """
    out = []
    for idx, row in df.iterrows():
        g = row.get("grade")
        grade_val = None if g is None or (isinstance(g, float) and math.isnan(g)) else str(g)
        out.append({
            "date": idx.strftime("%Y-%m-%d"),
            "ndx": _num(row["ndx"], 2),
            "pe": _num(row["pe"], 2),
            "pe_pct": _num(row["pe_pct"], 1),
            "ma200": _num(row["ma200"], 2),
            "dev_pct": _num(row["dev_pct"], 2),
            "vix": _num(row["vix"], 2),
            "pe_score": _num(row["pe_score"], 1),
            "ma_score": _num(row["ma_score"], 1),
            "vix_score": _num(row["vix_score"], 1),
            "total": _num(row["total"], 1),
            "grade": grade_val,
        })
    return out


def latest_snapshot(records: List[Dict]) -> Dict:
    """Build latest snapshot blob for the dashboard."""
    last = records[-1]
    return {
        "date": last["date"],
        "ndx": last["ndx"],
        "pe": last["pe"],
        "pe_pct": last["pe_pct"],
        "ma200": last["ma200"],
        "dev_pct": last["dev_pct"],
        "vix": last["vix"],
        "pe_score": last["pe_score"],
        "ma_score": last["ma_score"],
        "vix_score": last["vix_score"],
        "total": last["total"],
        "grade": last["grade"],
    }


# ============================================================================
# 5. Main
# ============================================================================

def main():
    out_dir = Path(__file__).resolve().parent
    try:
        df = fetch_market_data()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    df = compute_indicators(df)
    df = apply_scoring(df)
    records = to_records(df)

    # Write full history
    history_path = out_dir / "ndx_history.json"
    history_path.write_text(
        json.dumps({"generated_at": datetime.now().isoformat(), "records": records},
                   ensure_ascii=False, separators=(",", ":"))
    )
    print(f"[OK] {len(records)} records -> {history_path}")

    # Write latest snapshot
    snap_path = out_dir / "ndx_snapshot.json"
    snap = latest_snapshot(records)
    snap_path.write_text(
        json.dumps({"generated_at": datetime.now().isoformat(),
                    "latest": snap},
                   ensure_ascii=False, indent=2)
    )
    print(f"[OK] latest snapshot -> {snap_path}")

    # Build self-contained index.html with embedded data
    payload = {
        "generated_at": datetime.now().isoformat(),
        "latest": snap,
        "records": records,
    }
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Use a non-conflicting delimiter for safe HTML inline
    data_block = (
        "/* === Embedded NDX data (auto-injected by fetch_data.py) === */\n"
        "window.NDX_DATA = " + payload_json + ";\n"
    )

    tpl_path = out_dir / "template.html"
    index_path = out_dir / "index.html"
    if tpl_path.exists():
        tpl = tpl_path.read_text(encoding="utf-8")

        # 1. Ensure echarts.min.js exists locally (download via Node if missing)
        echarts_path = out_dir / "echarts.min.js"
        if not echarts_path.exists():
            print("[..] Fetching echarts library (one-time)...")
            _download_echarts(echarts_path)

        # 2. Reference local echarts file (no CDN dependency)
        echarts_tag = '<script src="./echarts.min.js"></' + 'script>'
        tpl = tpl.replace("<!-- __ECHARTS_CDN__ -->", echarts_tag)

        # 3. Inline the data
        data_block = (
            "/* === Embedded NDX data (auto-injected by fetch_data.py) === */\n"
            "window.NDX_DATA = " + payload_json + ";\n"
        )
        tpl = tpl.replace("/* __DATA_INJECTION__ */", data_block)

        index_path.write_text(tpl, encoding="utf-8")
        print(f"[OK] dashboard -> {index_path} (open directly in browser)")
    else:
        print(f"[WARN] {tpl_path} not found, skipping dashboard build")

    # Pretty summary
    last = records[-1]
    print("\n=== Latest Snapshot ===")
    print(f"  Date        : {last['date']}")
    print(f"  NDX         : {last['ndx']:.2f}")
    print(f"  PE          : {last['pe']:.2f}  (percentile: {last['pe_pct']}%)")
    print(f"  MA200       : {last['ma200']:.2f}  (deviation: {last['dev_pct']:+.2f}%)")
    print(f"  VIX         : {last['vix']:.2f}")
    print(f"  Scores      : PE={last['pe_score']}  MA={last['ma_score']}  VIX={last['vix_score']}")
    print(f"  Composite   : {last['total']}  Grade: {last['grade']}")


if __name__ == "__main__":
    main()
