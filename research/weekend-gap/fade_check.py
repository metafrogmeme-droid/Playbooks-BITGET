"""Robustness of the weekend fade: enter Sat 13:00 against the Fri-close->Sat-noon move, exit Mon 09:15."""
import math
import sys

sys.path.insert(0, ".")
from weekend_gap import FRI_CLOSE, MON_0915, SAT_13, SAT_NOON, TAKER, at, load, tstat, weekends
import glob

syms = sorted(p[:-9] for p in glob.glob("*_15m.json"))
data = {s: load(s) for s in syms}
first = min(min(v) for v in data.values()).date()
last = max(max(v) for v in data.values()).date()
rows = []  # (friday, symbol, signal, fade return)
for fri in weekends(first, last):
    for s in syms:
        v = [at(data[s], fri, *p) for p in (FRI_CLOSE, SAT_NOON, SAT_13, MON_0915)]
        if None in v:
            continue
        sig, nxt = v[1] / v[0] - 1, v[3] / v[2] - 1
        if sig:
            rows.append((fri, s, sig, -math.copysign(1, sig) * nxt))


def per_weekend(sel):
    by = {}
    for fri, s, sig, r in sel:
        by.setdefault(fri, []).append(r)
    return [sum(x) / len(x) for f, x in sorted(by.items()) if len(x) >= 3]


def show(label, sel):
    pw = per_weekend(sel)
    if not pw:
        return
    g = sum(pw) / len(pw)
    nets = "  ".join(f"net@{c}bp spread {(g - 2*TAKER - c/1e4)*1e4:+5.1f}bp" for c in (2, 10, 20))
    print(f"{label:34s} weekends={len(pw):3d} trades={len(sel):4d} gross={g*1e4:+6.1f}bp t={tstat(pw):+5.2f} | {nets}")


show("all", rows)
fr = sorted({r[0] for r in rows}); mid = fr[len(fr) // 2]
show("first half of weekends", [r for r in rows if r[0] < mid])
show("second half of weekends", [r for r in rows if r[0] >= mid])
for lo, hi in ((0, 0.005), (0.005, 0.01), (0.01, 0.02), (0.02, 1)):
    show(f"|Sat move| {lo*100:.1f}%-{hi*100:.1f}%", [r for r in rows if lo <= abs(r[2]) < hi])
show("Sat move up (fade = short)", [r for r in rows if r[2] > 0])
show("Sat move down (fade = long)", [r for r in rows if r[2] < 0])
# leave-one-symbol-out: does any single name carry it?
worst = min(((s, sum(per_weekend([r for r in rows if r[1] != s])) / len(per_weekend([r for r in rows if r[1] != s]))) for s in syms), key=lambda x: x[1])
print(f"\nleave-one-symbol-out: weakest result drops {worst[0]} -> gross {worst[1]*1e4:+.1f}bp")
# leave-one-weekend-out
pw = per_weekend(rows)
print("largest single-weekend contributions (bp):", sorted((round(x * 1e4) for x in pw), key=abs)[-5:])
print("gross without the 3 best weekends:", round(sum(sorted(pw)[:-3]) / (len(pw) - 3) * 1e4, 1), "bp")

# Baseline: always long from Sat 13:00 to Mon 09:15, no signal at all.
base = []
for fri in weekends(first, last):
    for s in syms:
        v = [at(data[s], fri, *p) for p in (SAT_13, MON_0915)]
        if None not in v:
            base.append((fri, s, -1.0, v[1] / v[0] - 1))
show("always long Sat 13:00->Mon 09:15", base)
show("  ...same, weekends with a down Sat", [b for b in base if any(r[0] == b[0] and r[1] == b[1] and r[2] < 0 for r in rows)])
