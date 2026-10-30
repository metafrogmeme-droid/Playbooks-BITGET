"""Next-best candidate: always long Sun 20:00 -> Mon 09:15 ET, net of taker fees, spread and funding."""
import glob
import sys

sys.path.insert(0, ".")
from weekend_gap import MON_0915, SUN_20, TAKER, at, load, tstat, weekends

FUNDING_PER_8H = 0.00008  # mid of the 0.4-1.3bp per 8h observed on NVDA/QQQ/TSLA/MSTR, Aug-Oct 2026
syms = sorted(p[:-9] for p in glob.glob("*_15m.json"))
data = {s: load(s) for s in syms}
first = min(min(v) for v in data.values()).date()
last = max(max(v) for v in data.values()).date()
pw = []
for fri in weekends(first, last):
    r = [v[1] / v[0] - 1 for s in syms
         if None not in (v := [at(data[s], fri, *p) for p in (SUN_20, MON_0915)])]
    if len(r) >= 5:
        pw.append((fri, sum(r) / len(r)))
funding = 2 * FUNDING_PER_8H  # 13.25 hours spans about two 8-hour funding stamps
half = len(pw) // 2
for label, sel in (("all", pw), ("first half", pw[:half]), ("second half", pw[half:])):
    x = [v for _, v in sel]
    g = sum(x) / len(x)
    nets = "  ".join(f"net@{c}bp spread {(g - 2*TAKER - c/1e4 - funding)*1e4:+5.1f}bp" for c in (2, 10, 20))
    print(f"{label:12s} weekends={len(x):3d} gross={g*1e4:+6.1f}bp t={tstat(x):+5.2f} won={sum(v>0 for v in x)/len(x)*100:3.0f}% | {nets}")
x = [v for _, v in pw]
print("worst weekend", round(min(x) * 1e4), "bp; best", round(max(x) * 1e4), "bp; without the 3 best:",
      round(sum(sorted(x)[:-3]) / (len(x) - 3) * 1e4, 1), "bp gross")
