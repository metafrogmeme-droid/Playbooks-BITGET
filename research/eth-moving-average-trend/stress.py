"""Volatility-target levels and stress tests for the chosen variant (run after fetch.py)."""
import calendar
import time

from sim import run, stats

ts = lambda s: calendar.timegm(time.strptime(s, "%Y-%m-%d")) * 1000
IS = (ts("2021-10-01"), ts("2024-01-01"))
OOS = (ts("2024-01-01"), None)
f = lambda d: f"{d['cagr']:6.1f}% {d['maxdd']:6.1f}% {d['sharpe']:5.2f}"
base = dict(longonly=True, voltarget=0.4)
cases = [
    ("winner", {}),
    ("fees x2", dict(fee=0.0012)),
    ("funding x3 (0.03%/8h)", dict(funding=0.0003)),
    ("40/160", dict(pairs=((40, 160),))),
    ("60/240", dict(pairs=((60, 240),))),
    ("30/150", dict(pairs=((30, 150),))),
]
for name, kw in cases:
    t, p, _ = run(**{**base, **kw})
    print(f"{name:24s} | IS {f(stats(t, p, *IS))} | OOS {f(stats(t, p, *OOS))} | full {f(stats(t, p, IS[0]))}")
for vt in (None, 0.6, 0.4, 0.3, 0.2):
    t, p, _ = run(longonly=True, voltarget=vt)
    print(f"long-only vol={vt} | IS {f(stats(t, p, *IS))} | OOS {f(stats(t, p, *OOS))}")
