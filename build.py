"""Build the Forex Rotation dashboard: a myfxbook-style heat map plus Relative
Rotation Graphs, on 4H and Daily only.

Universe: the eight majors of the myfxbook heat map -- USD EUR GBP JPY CHF CAD AUD
NZD -- and all C(8,2) = 28 crosses between them, read from OANDA on TradingView.
myfxbook itself cannot be the source: every page and feed there has sat behind a
Cloudflare bot challenge since 2026-09-08 (still 403 on 2026-09-25, including the
heat map), and its only price feed was weekly anyway. See the dashboard notes.

No benchmark index. With the full matrix in hand, each currency's strength is the
geometric mean of its rate against the other seven, and the benchmark is the
equal-weighted basket of those eight -- which is identically 1, because each pair
enters one index as +log rate and another as -log rate. So:

  Currencies RRG   RS = currency index (the basket is the unit)
  Pairs RRG        RS = the pair price itself, against that same unit

Dropping DXY also removed both grid bugs of the earlier build: every symbol is an
OANDA pair on one 4H grid, so 4H bars are pulled natively -- no resampling from
1H, no DST phase offset to derive, no session-stamp mismatch.

COMPLETED BARS ONLY. The scheduled run fires five minutes after each 4H close,
when the newest 4H bar is five minutes old; plotting it would add a near-empty
point to every tail. So the forming bar is dropped on both timeframes. The 4H view
therefore moves every run and the Daily view once a day, when the FX day closes
at 17:00 New York.

TradingView stamps a daily FX bar at the session OPEN (21:00 UTC), a day behind
the trading day it covers -- session_date() corrects the label.

    python build.py            # rebuild from the bar cache
    python build.py --refresh  # re-pull bars (TradingView on TV_CDP_PORT, default 9222)
"""
import json, math, os, subprocess, sys, time, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "bars_cache.json")
# The GitHub Actions run sets FX_FETCHER=fetch_bars_ws.mjs (TradingView's websocket,
# no Desktop needed) and NODE_EXE=node; both return the same bars.
FETCHER = os.path.join(ROOT, os.environ.get("FX_FETCHER", "fetch_bars.mjs"))
OUT_HTML = os.path.join(ROOT, "forex_rrg.html")
OUT_JSON = os.path.join(ROOT, "forex_rrg_data.json")
OUT_STAMP = os.path.join(ROOT, "built_4h_bar.txt")   # read by run_4h.ps1's data guard
NODE = os.environ.get("NODE_EXE", r"C:\Program Files\nodejs\node.exe")

CCY = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]
CCY_NAME = {"USD": "US dollar", "EUR": "Euro", "GBP": "Pound sterling",
            "JPY": "Japanese yen", "CHF": "Swiss franc", "CAD": "Canadian dollar",
            "AUD": "Australian dollar", "NZD": "New Zealand dollar"}
# The 28 crosses in market-standard naming (priority EUR GBP AUD NZD USD CAD CHF JPY).
PAIRS = ["EURUSD", "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
         "GBPUSD", "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
         "AUDUSD", "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
         "NZDUSD", "NZDJPY", "NZDCHF", "NZDCAD",
         "USDJPY", "USDCHF", "USDCAD",
         "CADJPY", "CADCHF",
         "CHFJPY"]
FEED = "OANDA"
FETCH = "1D:400,240:400"

WINDOW = 60      # z-score lookback, bars
ROC = 10         # momentum span, bars
TAIL = 2         # trailing bars behind the head
MIN_BARS = WINDOW + ROC + TAIL + 5

# periods: (bars back, short label, description) -- heat map tabs and table columns
TIMEFRAMES = [
    {"key": "240", "label": "4H", "secs": 4 * 3600, "stale_days": 4,
     "reach": "about 10 trading days",
     "periods": [(1, "4H", "last 4H candle"), (6, "24H", "last six 4H candles")]},
    {"key": "1D", "label": "Daily", "secs": 24 * 3600, "stale_days": 5,
     "reach": "about 12 weeks",
     "periods": [(1, "1D", "last daily candle"), (5, "1W", "last five sessions")]},
]


def log(m):
    print(m, flush=True)


def session_date(epoch):
    """Trading day of a daily FX bar stamped at the session open (21/22:00 UTC)."""
    return (pd.Timestamp(epoch, unit="s") + pd.Timedelta(hours=4)).date()


def now_utc():
    return pd.Timestamp.now("UTC").tz_localize(None)


# ---------------------------------------------------------------- prices

def fetch(refresh):
    if refresh or not os.path.exists(CACHE):
        syms = [f"{FEED}:{p}" for p in PAIRS]
        log(f"pulling {len(syms)} pairs x {FETCH} from TradingView "
            f"(CDP port {os.environ.get('TV_CDP_PORT', '9222')})")
        p = subprocess.run([NODE, FETCHER, CACHE, FETCH] + syms,
                           capture_output=True, text=True, timeout=1800)
        for line in (p.stdout or "").splitlines():
            log("  " + line)
        if p.returncode != 0:
            raise SystemExit("bar fetch failed: " + (p.stderr or "")[:500])
    return json.load(open(CACHE, encoding="utf-8"))


def frame(raw, tf):
    """Completed closes for one timeframe as a DataFrame, one column per pair."""
    src = raw.get(tf["key"]) or {}
    missing = [p for p in PAIRS if not src.get(f"{FEED}:{p}")]
    if missing:
        # Every currency index needs all seven of its legs, so a hole is fatal
        # rather than something to plot around.
        raise SystemExit(f"{tf['label']}: no bars for {', '.join(missing)}; rerun with --refresh")

    cutoff = now_utc()
    cols = {}
    for p in PAIRS:
        bars = [b for b in src[f"{FEED}:{p}"]
                if pd.Timestamp(b[0], unit="s") + pd.Timedelta(seconds=tf["secs"]) <= cutoff]
        key = session_date if tf["key"] == "1D" else (lambda t: pd.Timestamp(t, unit="s"))
        s = pd.Series([c for _, c in bars], index=[key(t) for t, _ in bars], dtype=float)
        cols[p] = s[~s.index.duplicated(keep="last")]
    df = pd.DataFrame(cols).sort_index().dropna()

    last = df.index[-1]
    last_day = last.date() if isinstance(last, pd.Timestamp) else last
    stale = (cutoff.date() - last_day).days
    if stale > tf["stale_days"]:
        raise SystemExit(f"{tf['label']}: newest completed bar is {stale} days old ({last}); "
                         f"rerun with --refresh")
    return df


def rate(df, a, b):
    """Price of one unit of a in b, from the pair itself or its reciprocal."""
    return df[a + b] if a + b in df else 1.0 / df[b + a]


def stamp(tf, v):
    if tf["key"] == "1D":
        return str(v)
    end = v + pd.Timedelta(seconds=tf["secs"])
    return f"{v:%Y-%m-%d %H:%M}-{end:%H:%M} UTC"


# ----------------------------------------------------------------- maths

def currency_indices(df):
    """Geometric currency indices and their basket (which should be exactly 1)."""
    logs = {c: sum(np.log(rate(df, c, x)) for x in CCY if x != c) / (len(CCY) - 1)
            for c in CCY}
    basket = sum(logs.values()) / len(CCY)
    resid = float(np.abs(basket).max())
    if resid > 1e-9:
        # Non-zero means an inverted leg or a missing cross: every mark would be
        # wrong but plausible, so refuse rather than publish it.
        raise SystemExit(f"basket is not the numeraire (max |log| {resid:.2e})")
    return {c: np.exp(v) for c, v in logs.items()}, np.exp(basket), resid


def rrg_points(px, bench):
    """JdK RS-Ratio / RS-Momentum, z-score replication. Last TAIL+1 points."""
    d = pd.concat({"p": px, "b": bench}, axis=1).dropna()
    if len(d) < MIN_BARS:
        return None
    rs = 100.0 * d["p"] / d["b"]
    ratio = 100 + (rs - rs.rolling(WINDOW).mean()) / rs.rolling(WINDOW).std()
    mom_raw = ratio.diff(ROC)
    mom = 100 + (mom_raw - mom_raw.rolling(WINDOW).mean()) / mom_raw.rolling(WINDOW).std()
    pts = pd.concat({"x": ratio, "y": mom}, axis=1).dropna()
    if len(pts) < TAIL + 1:
        return None
    tail = pts.iloc[-(TAIL + 1):]
    if not all(map(math.isfinite, tail.to_numpy().ravel())):
        return None
    return [[round(float(a), 3), round(float(b), 3)] for a, b in tail.to_numpy()]


def quadrant(x, y):
    if x >= 100:
        return "Leading" if y >= 100 else "Weakening"
    return "Improving" if y >= 100 else "Lagging"


def pct(s, n):
    return round((float(s.iloc[-1]) / float(s.iloc[-1 - n]) - 1) * 100, 3)


def point(t, name, s, bench, periods, **extra):
    p = rrg_points(s, bench)
    if p is None:
        return None
    (x, y), (x0, y0) = p[-1], p[0]
    return dict(t=t, n=name, x=x, y=y, q=quadrant(x, y), tail=p,
                dx=round(x - x0, 3), dy=round(y - y0, 3),
                chg=[pct(s, n) for n, _, _ in periods], **extra)


def build_tf(raw, tf):
    df = frame(raw, tf)
    idx, basket, resid = currency_indices(df)
    periods = tf["periods"]

    heat = []
    for n, key, desc in periods:
        matrix = {a: {b: pct(rate(df, a, b), n) for b in CCY if b != a} for a in CCY}
        strength = {c: pct(idx[c], n) for c in CCY}
        heat.append({"key": key, "desc": desc, "n": n, "matrix": matrix, "strength": strength})

    ccy_pts = [point(c, CCY_NAME[c], idx[c], basket, periods,
                     level=round(float(idx[c].iloc[-1] / idx[c].iloc[0] * 100), 2))
               for c in CCY]
    unit = pd.Series(1.0, index=df.index)
    pair_pts = [point(p, f"{CCY_NAME[p[:3]]} / {CCY_NAME[p[3:]]}", df[p], unit, periods,
                      base=p[:3], quote=p[3:], level=round(float(df[p].iloc[-1]), 5))
                for p in PAIRS]
    dropped = [p for p, v in zip(CCY + PAIRS, ccy_pts + pair_pts) if v is None]
    ccy_pts = [v for v in ccy_pts if v]
    pair_pts = [v for v in pair_pts if v]

    log(f"{tf['label']:<6} {len(df)} completed bars, last {stamp(tf, df.index[-1])}"
        f"  basket residual {resid:.1e}"
        + (f"  dropped: {', '.join(dropped)}" if dropped else ""))
    log("       strength " + "  ".join(f"{c} {heat[0]['strength'][c]:+.2f}%" for c in
                                       sorted(CCY, key=lambda c: -heat[0]['strength'][c])))
    return {"key": tf["key"], "label": tf["label"], "reach": tf["reach"],
            "bars": len(df), "last": stamp(tf, df.index[-1]),
            "periods": [{"key": k, "desc": d, "n": n} for n, k, d in periods],
            "heat": heat, "ccy": ccy_pts, "pairs": pair_pts,
            "_last_raw": str(df.index[-1])}


def main():
    raw = fetch("--refresh" in sys.argv)
    views = [build_tf(raw, tf) for tf in TIMEFRAMES]
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M"), "tz": "Bangkok (UTC+7)",
            "ccy": CCY, "pairs": len(PAIRS), "window": WINDOW, "roc": ROC, "tail": TAIL,
            "feed": FEED}
    four_h = next(v for v in views if v["key"] == "240")
    for v in views:
        v.pop("_last_raw")
    json.dump({"meta": meta, "views": views}, open(OUT_JSON, "w", encoding="utf-8"))

    from render import render
    html = render(meta, views)
    open(OUT_HTML, "w", encoding="utf-8").write(html)
    open(OUT_STAMP, "w", encoding="utf-8").write(four_h["last"])
    log(f"wrote {os.path.basename(OUT_HTML)} ({len(html):,} bytes); 4H stamp {four_h['last']}")
    return 0


if __name__ == "__main__":
    # The scheduled runner keeps STDOUT only (stderr noise once ballooned a log to
    # 7 GB), so a fatal message must go to stdout or the log shows a bare exit=1.
    try:
        sys.exit(main())
    except SystemExit as e:
        if e.code not in (None, 0):
            print(f"FATAL: {e.code}", flush=True)
            sys.exit(1)
        raise
