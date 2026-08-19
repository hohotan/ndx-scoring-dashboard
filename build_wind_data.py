"""
Build the NDX scoring dashboard dataset from Wind-sourced data.

Data sources (all from Wind, pulled via the wind-finance connector and saved
to the tool-results directory):
  - NDX.GI daily K-line  -> NDX close (price)
  - VIX.GI daily K-line  -> VIX close
  - EDB G0011659 (市盈率:纳斯达克综合指数) daily -> used as NDX100 PE proxy
    (Wind has no standalone NDX100 PE time series; Composite PE is the closest
     Wind-sourced valuation series and is highly correlated with NDX100 PE.)

Scoring is aligned to the reference "纳斯达克100打分系统":
  PE score  = 30 * (1 - pe_pct/100)            [0..30]
  MA score  = 0 if dev>=0 else 40*min(1,-dev/20) [0..40]   (0 when above MA200)
  VIX score = min(30, max(0, (vix-15)*2))      [0..30]
  total = pe_score + ma_score + vix_score
  grade: A>=80 B>=60 C>=40 D>=20 E<20
"""
from __future__ import annotations
import json, os, math, sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
# Stable cache populated from the Wind connector output. The connector writes timestamped
# files into its own tool-results dir; the refresh automation copies the latest fetches
# here under fixed names so build_wind_data.py never depends on those timestamps.
CACHE = ROOT / "wind_cache"
NDX_FILE = CACHE / "ndx_kline.txt"
VIX_FILE = CACHE / "vix_kline.txt"
PE_FILE  = CACHE / "pe_edb.txt"

# Guard: this script needs Wind-sourced data files produced by the Wind connector.
# In CI (GitHub Actions) those files are absent, so we no-op instead of clobbering the
# Wind-generated dashboard. The dashboard is regenerated locally (with the Wind terminal)
# and pushed; the cron auto-refresh has been disabled for this reason.
if not CACHE.exists():
    print("wind_cache directory not found at:", CACHE)
    print("Skipping regeneration (no Wind data cached). No files were changed.")
    sys.exit(0)

def ymd(s: str) -> str:
    s = str(s)
    if len(s) >= 10 and s[4] == '-':
        return s[:10]
    # maybe 20060817
    if len(s) >= 8 and s[4] != '-':
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]

def load_kline(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    blk = d["data"]
    cols = [c["name"] for c in blk["columns"]]
    mi = cols.index("MATCH")
    ti = cols.index("TIME")
    out = {}
    for row in blk["rows"]:
        try:
            date = ymd(row[ti])
            val = float(row[mi])
        except (ValueError, TypeError, IndexError):
            continue
        out[date] = val
    return out

def load_pe(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    blk = d["data"]["data"][0]
    dates = blk["date"]
    values = blk["value"]
    out = {}
    for dt, vv in zip(dates, values):
        if vv is None:
            continue
        try:
            out[ymd(dt)] = float(vv)
        except (ValueError, TypeError):
            continue
    return out

ndx = load_kline(NDX_FILE)
vix = load_kline(VIX_FILE)
pe  = load_pe(PE_FILE)
print(f"loaded: NDX={len(ndx)} VIX={len(vix)} PE={len(pe)}")
print("NDX range:", min(ndx), max(ndx))
print("PE  range:", min(pe), max(pe))

# Align on NDX dates that have all three
dates = sorted(set(ndx) & set(vix) & set(pe))
print("aligned common dates:", len(dates), dates[0], dates[-1])

# Build price/pe/vix frames for rolling calcs
s_ndx = pd.Series({d: ndx[d] for d in dates})
s_pe  = pd.Series({d: pe[d] for d in dates})

# 200-day MA on price
ma200 = s_ndx.rolling(window=200, min_periods=50).mean()
# 10-year PE percentile (trailing ~2520 sessions)
pe_pct = s_pe.rolling(window=2520, min_periods=1260).rank(pct=True) * 100.0

def score_pe(p):
    if p is None or (isinstance(p, float) and math.isnan(p)): return None
    return round(max(0.0, 30.0 * (1.0 - p / 100.0)), 1)

def score_ma(dev):
    if dev is None or (isinstance(dev, float) and math.isnan(dev)): return None
    if dev >= 0:
        return 0.0
    return round(float(np.clip(40.0 * (-dev) / 20.0, 0.0, 40.0)), 1)

def score_vix(v):
    if v is None or (isinstance(v, float) and math.isnan(v)): return None
    return round(float(np.clip((v - 15.0) * 2.0, 0.0, 30.0)), 1)

def total_grade(t):
    if t is None: return None
    if t >= 80: return "A"
    if t >= 60: return "B"
    if t >= 40: return "C"
    if t >= 20: return "D"
    return "E"

def _num(v, d=2):
    if v is None: return None
    try: f = float(v)
    except (TypeError, ValueError): return None
    if math.isnan(f): return None
    return round(f, d)

records = []
for d in dates:
    n = ndx[d]; v = vix[d]; p = pe[d]
    m = ma200.get(d)
    m = None if (m is None or (isinstance(m, float) and math.isnan(m))) else float(m)
    dev = None if m is None else (n / m - 1.0) * 100.0
    pct = pe_pct.get(d)
    pct = None if (pct is None or (isinstance(pct, float) and math.isnan(pct))) else float(pct)
    pe_s = score_pe(pct)
    ma_s = score_ma(dev)
    vix_s = score_vix(v)
    tot = None
    if pe_s is not None and ma_s is not None and vix_s is not None:
        tot = round(pe_s + ma_s + vix_s, 1)
    grade = total_grade(tot)
    records.append({
        "date": d,
        "ndx": _num(n, 2),
        "pe": _num(p, 2),
        "pe_pct": _num(pct, 1),
        "ma200": _num(m, 2),
        "dev_pct": _num(dev, 2),
        "vix": _num(v, 2),
        "pe_score": _num(pe_s, 1),
        "ma_score": _num(ma_s, 1),
        "vix_score": _num(vix_s, 1),
        "total": _num(tot, 1),
        "grade": grade,
    })

print("total records:", len(records))

# --- Override the latest record with the REAL NDX100 PE + 10y percentile ---
# Wind EDB has no standalone NDX100 PE daily series; the historical PE trend above
# uses the Nasdaq Composite PE (G0011659) as a proxy. But Wind's get_index_fundamentals
# returns the REAL NDX100 PE (30.9848) and its 10y percentile (49.82%) for the latest
# trading day, which is exactly what the reference app uses. Override the latest point so
# the headline snapshot matches the reference, while history stays on the proxy series.
OVERRIDE_FILE = ROOT / "wind_ndx100_pe_latest.json"
if OVERRIDE_FILE.exists():
    ov = json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
    last_rec = records[-1]
    if last_rec["date"] == ov.get("date") or "pe" in ov:
        real_pe = float(ov["pe"])
        real_pct = float(ov["pe_pct"])
        last_rec["pe"] = _num(real_pe, 2)
        last_rec["pe_pct"] = _num(real_pct, 1)
        last_rec["pe_score"] = score_pe(real_pct)
        # recompute total + grade
        pe_s = last_rec["pe_score"]; ma_s = last_rec["ma_score"]; vix_s = last_rec["vix_score"]
        if pe_s is not None and ma_s is not None and vix_s is not None:
            last_rec["total"] = round(pe_s + ma_s + vix_s, 1)
        last_rec["grade"] = total_grade(last_rec["total"])
        print(f"overrode latest {last_rec['date']} PE -> {real_pe} (pct {real_pct}%) [NDX100 direct valuation]")
    else:
        print(f"override file date {ov.get('date')} != latest {last_rec['date']}; skipping override")
else:
    print("wind_ndx100_pe_latest.json not found; latest PE stays on Composite proxy")

last = records[-1]
print("LATEST:", last["date"], "ndx", last["ndx"], "pe", last["pe"], "pe_pct", last["pe_pct"],
      "dev", last["dev_pct"], "vix", last["vix"], "PE", last["pe_score"], "MA", last["ma_score"],
      "VIX", last["vix_score"], "total", last["total"], "grade", last["grade"])

# Write history + snapshot
(ndx_hist := ROOT / "ndx_history.json").write_text(
    json.dumps({"generated_at": datetime.now().isoformat(), "records": records,
                "source": "Wind: NDX.GI price, VIX.GI, EDB G0011659 PE proxy; latest PE/percentile = NDX.GI direct valuation"},
               ensure_ascii=False, separators=(",", ":"))
)
snap = {k: last[k] for k in last}
(ndx_snap := ROOT / "ndx_snapshot.json").write_text(
    json.dumps({"generated_at": datetime.now().isoformat(), "latest": snap,
                "source": "Wind: NDX.GI price, VIX.GI, EDB G0011659 PE proxy; latest PE/percentile = NDX.GI direct valuation"},
               ensure_ascii=False, indent=2)
)
print("wrote ndx_history.json + ndx_snapshot.json")

# Build index.html from template.html (same injection as fetch_data.py)
payload = {"generated_at": datetime.now().isoformat(), "latest": snap, "records": records,
           "source": "Wind"}
payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
tpl = (ROOT / "template.html").read_text(encoding="utf-8")
echarts_tag = '<script src="./echarts.min.js"></' + 'script>'
tpl = tpl.replace("<!-- __ECHARTS_CDN__ -->", echarts_tag)
data_block = "/* === Embedded NDX data (auto-injected by build_wind_data.py) === */\nwindow.NDX_DATA = " + payload_json + ";\n"
tpl = tpl.replace("/* __DATA_INJECTION__ */", data_block)
(ROOT / "index.html").write_text(tpl, encoding="utf-8")
print("wrote index.html")
