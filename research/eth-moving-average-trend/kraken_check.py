"""Cross-venue check: rerun the v0.2.0 design on Kraken spot 4h candles and compare with Bitget perps, same window."""
import calendar
import csv
import glob
import sys
import time

import numpy as np

import sim

KRAKEN = {"BTCUSDT": "XBTUSD", "ETHUSDT": "ETHUSD", "SOLUSDT": "SOLUSD", "XRPUSDT": "XRPUSD"}
ts = lambda s: calendar.timegm(time.strptime(s, "%Y-%m-%d")) * 1000
H = 4 * 3600 * 1000


def kraken_closes(folder):
    out = {}
    for sym, pair in KRAKEN.items():
        path = glob.glob(f"{folder}/*{pair}_240.csv")[0]
        out[sym] = {int(float(r[0])) * 1000: float(r[4]) for r in csv.reader(open(path))}
    return out


def results(label):
    # warm-up: 200 bars of each series before the first trade
    a = ts("2024-01-01") + 200 * H
    b = ts("2025-12-31")
    for name, kw in (("v0.2.0 long-only + vol target", dict(longonly=True, voltarget=0.4)), ("original long+short", {})):
        t, p, _ = sim.run(funding=0, warm=0, **kw)
        print(f"{label:16s} {name:30s} {sim.stats(t, p, a, b)}")


def load_into_sim(closes):
    start = max(min(v) for v in closes.values())
    end = min(max(v) for v in closes.values())
    T = np.arange(start, end + 1, H)
    C = {}
    for s, series in closes.items():
        c = np.array([series.get(int(t), np.nan) for t in T])
        for i in range(1, len(c)):
            if np.isnan(c[i]):
                c[i] = c[i - 1]
        C[s] = c
    sim.T, sim.C = T, C
    sim.R = {s: np.r_[0, C[s][1:] / C[s][:-1] - 1] for s in sim.SYMS}
    sim.VOL = {s: sim.rvol(sim.R[s]) for s in sim.SYMS}


# Bitget, restricted to the same 2024-2025 span so both venues have identical warm-up
bitget = {s: {t: v for t, v in zip(sim.T, sim.C[s]) if ts("2024-01-01") <= t <= ts("2025-12-31")} for s in sim.SYMS}
load_into_sim(bitget)
results("Bitget perps")
load_into_sim(kraken_closes(sys.argv[1]))
results("Kraken spot")
