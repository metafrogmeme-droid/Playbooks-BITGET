"""Step 0: is weekend information in Bitget US-stock perps only partly priced before the Monday cash open?

For every regular weekend (no exchange holiday on the Friday or Monday) and every symbol, read the
perp's own 15-minute closes at fixed New York times and test whether an early weekend move predicts
the later move. Statistics are computed on the per-weekend average across symbols, because symbols
move together and pooling them would overstate the sample.
"""
import datetime as dt
import glob
import json
import math
import sys
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TAKER = 0.0006
# NYSE full-day closures on a Friday or Monday, plus the 2025-11-28 half day, 2025-08 to 2026-10.
HOLIDAYS = {"2025-09-01", "2025-11-28", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
            "2026-06-19", "2026-07-03", "2026-09-07"}


def load(sym):
    rows = json.load(open(f"{sym}_15m.json"))
    # key each bar by its close time in New York
    return {dt.datetime.fromtimestamp(t / 1000, ET) + dt.timedelta(minutes=15): c
            for t, (o, h, l, c, v, qv) in rows}


def at(closes, friday, days, hh, mm):
    d = friday + dt.timedelta(days=days)
    return closes.get(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET))


def weekends(start, end):
    d = start
    while d.weekday() != 4:
        d += dt.timedelta(days=1)
    while d + dt.timedelta(days=3) <= end:
        mon = d + dt.timedelta(days=3)
        if d.isoformat() not in HOLIDAYS and mon.isoformat() not in HOLIDAYS:
            yield d
        d += dt.timedelta(days=7)


# legs: (name, signal start, signal end / entry, exit), each point = (days after Friday, hour, minute)
FRI_CLOSE = (0, 16, 0)
SAT_NOON = (1, 12, 0)
SUN_20 = (2, 20, 0)
MON_0915 = (3, 9, 15)
MON_1030 = (3, 10, 30)
MON_1600 = (3, 16, 0)
SAT_13 = (1, 13, 0)
SUN_21 = (2, 21, 0)
TESTS = [
    ("A  Fri close->Sat noon predicts Sat noon->Mon 09:15 (flat before open, kit rule)", FRI_CLOSE, SAT_NOON, SAT_NOON, MON_0915),
    ("B  Fri close->Sun 20:00 predicts Sun 20:00->Mon 09:15 (flat before open, kit rule)", FRI_CLOSE, SUN_20, SUN_20, MON_0915),
    ("C  Fri close->Mon 09:15 predicts Mon 09:15->10:30 (holds through the open)", FRI_CLOSE, MON_0915, MON_0915, MON_1030),
    ("D  Fri close->Mon 09:15 predicts Mon 09:15->16:00 (holds through Monday)", FRI_CLOSE, MON_0915, MON_0915, MON_1600),
    ("E  as A, but enter one hour after the signal (Sat 13:00): separates reversal from a noisy print", FRI_CLOSE, SAT_NOON, SAT_13, MON_0915),
    ("F  as B, but enter one hour after the signal (Sun 21:00)", FRI_CLOSE, SUN_20, SUN_21, MON_0915),
]


def tstat(xs):
    n = len(xs)
    if n < 3:
        return float("nan")
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else float("nan")


def main(spread_rt):
    syms = sorted(p[:-9] for p in glob.glob("*_15m.json"))
    data = {s: load(s) for s in syms}
    first = min(min(v) for v in data.values()).date()
    last = max(max(v) for v in data.values()).date()
    qqq = data.get("QQQUSDT")
    cost = 2 * TAKER + spread_rt
    print(f"{len(syms)} symbols, {first} to {last}, round-trip cost {cost*1e4:.0f}bp "
          f"(taker {2*TAKER*1e4:.0f}bp + spread {spread_rt*1e4:.0f}bp)\n")
    for name, p0, p1, pe, p2 in TESTS:
        for hedged in (False, True):
            per_weekend = []   # (mean gross pnl, mean signal*next correlation sample)
            pairs = []
            for fri in weekends(first, last):
                if hedged:
                    q = [at(qqq, fri, *p) for p in (p0, p1, pe, p2)] if qqq else [None]
                    if None in q:
                        continue
                    qs, qn = q[1] / q[0] - 1, q[3] / q[2] - 1
                pnl = []
                for s in syms:
                    if hedged and s == "QQQUSDT":
                        continue
                    v = [at(data[s], fri, *p) for p in (p0, p1, pe, p2)]
                    if None in v:
                        continue
                    sig, nxt = v[1] / v[0] - 1, v[3] / v[2] - 1
                    if hedged:
                        sig, nxt = sig - qs, nxt - qn
                    if sig == 0:
                        continue
                    pairs.append((sig, nxt))
                    pnl.append(math.copysign(1, sig) * nxt)
                if len(pnl) >= 5:
                    per_weekend.append(sum(pnl) / len(pnl))
            if not per_weekend:
                continue
            n = len(per_weekend)
            gross = sum(per_weekend) / n
            sx = sum(a for a, _ in pairs) / len(pairs); sy = sum(b for _, b in pairs) / len(pairs)
            cov = sum((a - sx) * (b - sy) for a, b in pairs)
            var = sum((a - sx) ** 2 for a, _ in pairs)
            beta = cov / var if var else float("nan")
            hit = sum(1 for x in per_weekend if x > 0) / n
            label = "QQQ-hedged" if hedged else "outright  "
            # a hedged trade pays costs on two legs
            c = cost * (2 if hedged else 1)
            print(f"{name}\n   {label} weekends={n:3d} slope={beta:+.3f} "
                  f"gross/trade={gross*1e4:+6.1f}bp t={tstat(per_weekend):+5.2f} weekends won={hit*100:3.0f}% "
                  f"net/trade={(gross-c)*1e4:+6.1f}bp")
        print()


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 0.0002)
