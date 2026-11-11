"""Extend 001's frozen limit-scanner book (benchmark/limit_scanner_1h, ends 2026-10-10)
with Bitget public 1h USDT-M candles and funding history from 2026-10-01 to now.

usage: python3 fetch_forward.py <frozen_dataset_dir> <out_dir>
Writes <out_dir>/<file>.csv.gz in the frozen format (timestamp,open,high,low,close,volume;
volume is base volume), <out_dir>/funding/<SYMBOL>.json and an overlap check against the
frozen book. Public endpoints only, no key.
"""
import csv, gzip, json, pathlib, sys, time, urllib.request
from datetime import datetime, timezone

START_MS = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
BASE = "https://api.bitget.com/api/v2/mix/market"
frozen, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
(out / "funding").mkdir(parents=True, exist_ok=True)


def get(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 ** attempt)
    raise RuntimeError(url)


def candles(sym):
    rows, end = {}, int(time.time() * 1000)
    while end > START_MS:
        d = get(f"{BASE}/history-candles?symbol={sym}&granularity=1H&productType=USDT-FUTURES&endTime={end}&limit=200")["data"]
        if not d:
            break
        for c in d:
            rows[int(c[0])] = c[1:6]
        first = min(int(c[0]) for c in d)
        if first >= end:
            break
        end = first - 1
        time.sleep(0.12)
    now_hour = int(time.time() // 3600 * 3600 * 1000)
    return sorted((t, v) for t, v in rows.items() if START_MS <= t < now_hour - 3600 * 1000)  # closed bars only


def funding(sym):
    rows = []
    for page in range(1, 20):
        d = get(f"{BASE}/history-fund-rate?symbol={sym}&productType=USDT-FUTURES&pageSize=100&pageNo={page}")["data"]
        if not d:
            break
        rows += [{"ms": int(x["fundingTime"]), "rate": float(x["fundingRate"])} for x in d]
        if min(int(x["fundingTime"]) for x in d) < START_MS:
            break
        time.sleep(0.12)
    return sorted([r for r in rows if r["ms"] >= START_MS], key=lambda r: r["ms"])


def frozen_rows(path):
    with gzip.open(path, "rt") as h:
        return {int(datetime.fromisoformat(r["timestamp"]).timestamp() * 1000): r for r in csv.DictReader(h)}


manifest = json.loads((frozen / "manifest.json").read_text())
report = {}
for key, entry in manifest["symbols"].items():
    sym = entry["file"].replace("_USDT_USDT.csv.gz", "") + "USDT"
    rows = candles(sym)
    with gzip.open(out / entry["file"], "wt", newline="") as h:
        w = csv.writer(h); w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for t, (o, hi, lo, c, v) in rows:
            w.writerow([datetime.fromtimestamp(t / 1000, timezone.utc).isoformat(), o, hi, lo, c, v])
    fz = frozen_rows(frozen / entry["file"])
    overlap = [(t, v) for t, v in rows if t in fz]
    max_close_diff = max((abs(float(v[3]) - float(fz[t]["close"])) / float(fz[t]["close"]) for t, v in overlap), default=None)
    fr = funding(sym)
    (out / "funding" / f"{sym}.json").write_text(json.dumps(fr))
    report[sym] = {"bars": len(rows), "first": rows[0][0] if rows else None, "last": rows[-1][0] if rows else None,
                   "overlap_bars": len(overlap), "max_close_rel_diff": max_close_diff, "funding_prints": len(fr)}
    print(sym, report[sym], flush=True)
(out / "fetch_report.json").write_text(json.dumps(report, indent=1))
