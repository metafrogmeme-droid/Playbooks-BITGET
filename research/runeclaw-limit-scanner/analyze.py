"""Break down one published version's backtest evidence: fees, sides, symbols, holds, sizing.

usage: python3 analyze.py pb_0.6.47.json
The what-if section re-prices the same trades. It is in-sample and only ranks ideas.
"""
import collections, json, statistics as st, sys

TAKER, MAKER = 0.0006, 0.0002
h = json.load(open(sys.argv[1]))
om = h["official_metrics"]; rep = om["reports"]
usdt = lambda s: float(s.split()[0])

print(f"{h['display_name']} v{h['version']}  window {om['actual_window_start']} -> {om['actual_window_end']}")
print(f"published: return {om['total_return_pct']}%  mdd {om['max_drawdown_pct']}%  PF {om['profit_factor']}  win {om['win_rate']}  margin_budget {om.get('margin_budget')}")
print("order types:", dict(collections.Counter((o["type"], o["time_in_force"], o.get("liquidity_side")) for o in rep["orders"])))

rows = []
for p in rep["positions"]:
    q = float(p["peak_qty"]); fee = sum(usdt(c) for c in p["commissions"]); net = usdt(p["realized_pnl"])
    rows.append(dict(sym=p["instrument_id"].split(".")[0], side=p["entry"], ret=p["realized_return"],
                     n_in=q * p["avg_px_open"], n_out=q * p["avg_px_close"], fee=fee, net=net, gross=net + fee,
                     hrs=(p["duration_ns"] or 0) / 3.6e12))

def line(label, rs, fee_fn=lambda x: x["fee"]):
    g = sum(x["gross"] for x in rs); f = sum(fee_fn(x) for x in rs); n = sum(x["n_in"] for x in rs)
    pnl = [x["gross"] - fee_fn(x) for x in rs]
    w = sum(v for v in pnl if v > 0); l = -sum(v for v in pnl if v <= 0)
    pf = w / l if l else float("inf")
    print(f"  {label:38} n={len(rs):3} gross {g:8.2f} fees {f:7.2f} net {g - f:8.2f} | edge {g / n * 1e4:6.1f} bp  cost {f / n * 1e4:5.1f} bp | PF {pf:4.2f}")

net = [x["net"] for x in rows]; wins = [v for v in net if v > 0]
w_ret = sum(x["ret"] for x in rows if x["ret"] > 0); l_ret = -sum(x["ret"] for x in rows if x["ret"] < 0)
print(f"net PnL {sum(net):.2f}  fees {sum(x['fee'] for x in rows):.2f}  net win rate {len(wins) / len(net):.3f}")
print(f"PF from net PnL {sum(wins) / -sum(v for v in net if v <= 0):.3f}  vs PF from unsized price returns {w_ret / l_ret:.4f}")

print("by side / symbol (taker fees as run):")
line("ALL", rows)
for s in ("BUY", "SELL"):
    line(f"entry {s}", [x for x in rows if x["side"] == s])
for sym in sorted({x["sym"] for x in rows}, key=lambda s: -sum(x["sym"] == s for x in rows)):
    line(sym, [x for x in rows if x["sym"] == sym])
print("never traded:", [s for s in h["trading_symbols"] if s not in {x["sym"] for x in rows}])

print("by holding time:")
for lo, hi, lab in ((0, 1, "<=1h"), (1, 4, "1-4h"), (4, 12, "4-12h"), (12, 1e9, ">12h")):
    rs = [x for x in rows if lo < x["hrs"] <= hi or (lo == 0 and x["hrs"] == 0)]
    if rs:
        line(lab, rs)

n_in = [x["n_in"] for x in rows]; mb = om.get("margin_budget") or 0
vals = [float(e["value"]) for e in rep["equity_curve"]]; peak = vals[0]; dd = 0
for v in vals:
    peak = max(peak, v); dd = max(dd, peak - v)
print(f"entry notional median {st.median(n_in):.0f} max {max(n_in):.0f} USDT = {max(n_in) / mb:.1f}x margin budget {mb}")
print(f"max drawdown {dd:.2f} USDT = {dd / vals[0] * 100:.2f}% of 1000 account, {dd / mb * 100:.1f}% of margin budget")
print("worst trades:", [(x["sym"], x["side"], f"{x['ret'] * 100:.1f}%", round(x["net"], 2)) for x in sorted(rows, key=lambda x: x["net"])[:5]])

print("what-ifs on the same trades (in-sample, not evidence):")
line("A as run: taker in, taker out", rows)
line("B maker entry, taker exit", rows, lambda x: x["n_in"] * MAKER + x["n_out"] * TAKER)
line("C maker entry and exit", rows, lambda x: (x["n_in"] + x["n_out"]) * MAKER)
line("D shorts only", [x for x in rows if x["side"] == "SELL"])
line("E without ETHUSDT", [x for x in rows if x["sym"] != "ETHUSDT"])
line("F without LABUSDT", [x for x in rows if x["sym"] != "LABUSDT"])
line("G B + shorts only", [x for x in rows if x["side"] == "SELL"], lambda x: x["n_in"] * MAKER + x["n_out"] * TAKER)
