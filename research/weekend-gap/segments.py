"""Average return per closure segment: weekend vs weekday overnight, per weekend/night, averaged across symbols."""
import datetime as dt
import glob
import sys

sys.path.insert(0, ".")
from weekend_gap import ET, HOLIDAYS, load, tstat

syms = sorted(p[:-9] for p in glob.glob("*_15m.json"))
data = {s: load(s) for s in syms}
first = min(min(v) for v in data.values()).date()
last = max(max(v) for v in data.values()).date()


def px(c, d, hh, mm):
    return c.get(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET))


def seg(label, start_day_filter, legs):
    """legs: list of (day offset, hh, mm) points; reports each consecutive leg and the whole span."""
    out = {i: [] for i in range(len(legs))}
    d = first
    while d <= last:
        days = [d + dt.timedelta(days=o) for o, _, _ in legs]
        if start_day_filter(d) and not any(x.isoformat() in HOLIDAYS for x in days):
            for i in range(len(legs)):
                a, b = (legs[i - 1], legs[i]) if i else (legs[0], legs[-1])
                r = []
                for s in syms:
                    p0 = px(data[s], d + dt.timedelta(days=a[0]), a[1], a[2])
                    p1 = px(data[s], d + dt.timedelta(days=b[0]), b[1], b[2])
                    if p0 and p1:
                        r.append(p1 / p0 - 1)
                if len(r) >= 5:
                    out[i].append(sum(r) / len(r))
        d += dt.timedelta(days=1)
    names = ["whole span"] + [f"{legs[i-1]} -> {legs[i]}" for i in range(1, len(legs))]
    hours = (dt.datetime(2000, 1, 1 + legs[-1][0], legs[-1][1], legs[-1][2]) - dt.datetime(2000, 1, 1 + legs[0][0], legs[0][1], legs[0][2])).total_seconds() / 3600
    print(label, f"({hours:.1f}h)")
    for i, n in enumerate(names):
        x = out[i]
        if x:
            print(f"   {n:32s} n={len(x):3d} mean={sum(x)/len(x)*1e4:+6.1f}bp t={tstat(x):+5.2f}")


seg("WEEKEND Fri 16:00 -> Mon 09:15", lambda d: d.weekday() == 4,
    [(0, 16, 0), (1, 12, 0), (1, 13, 0), (2, 20, 0), (3, 9, 15), (3, 9, 45)])
seg("WEEKDAY NIGHTS Mon-Thu 16:00 -> next day 09:15", lambda d: d.weekday() in (0, 1, 2, 3),
    [(0, 16, 0), (1, 9, 15), (1, 9, 45)])
seg("WEEKDAY CASH SESSION 09:30 -> 16:00", lambda d: d.weekday() < 5, [(0, 9, 30), (0, 16, 0)])
