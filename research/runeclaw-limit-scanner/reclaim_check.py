"""Is the reclaim variant's edge a fill-model artifact?

001's pre-registered V1/V3 fill a resting limit only when the fill bar's close is back
through the limit, and book the entry at the limit price. A live resting limit fills on
the touch, before that close is known, so this keeps the good fills, drops the bad ones,
and enters at a price no order placed after the close could get.

This runs 001's simulator unchanged except for one swap: with ENTER_AT_CLOSE, a reclaim
entry is booked at the fill bar's close (what a bot can do once it has seen the reclaim),
with no same-bar exit stepping. Everything here is post-hoc: the windows were already read,
and these rows cannot pass 001's forward bar.

usage: python3 reclaim_check.py <path-to-001> <forward_1h_dir> > reclaim_check.json
<forward_1h_dir> is the output of fetch_forward.py.
"""
import json, sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
FORWARD = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(ROOT))

import bot.core.limit_shadow as ls  # noqa: E402
from bot.core.limit_scanner import params_from_preset  # noqa: E402
from bot.skills.skill_registry import RunStrategySkill  # noqa: E402

ENTER_AT_CLOSE = False
_original_open = ls._open_position


def _open(order, bar, positions, meta, params, spec, trades):
    if not (ENTER_AT_CLOSE and order.get("reclaim")):
        return _original_open(order, bar, positions, meta, params, spec, trades)
    if order["symbol"] in positions:
        return
    px = bar[4]
    positions[order["symbol"]] = ls.ExitState(side=order["side"], entry=px, stop=order["stop"],
                                              atr=order["atr"], opened_ms=bar[0])
    meta[order["symbol"]] = {
        "symbol": order["symbol"], "side": order["side"], "entry": px, "fill_ms": bar[0],
        "decision_ms": order["placed_ms"], "points": order["points"], "class": order["class"],
        "gross_bp": 0.0, "exit_share": 0.0, "reasons": [],
    }
    # Entered at the close: the fill bar has no path left, so stepping starts on the next bar.


ls._open_position = _open

frozen, failed = ls.load_bars(ROOT / "benchmark" / "limit_scanner_1h")
manifest = json.loads((ROOT / "benchmark" / "limit_scanner_1h" / "manifest.json").read_text())
extended = {}
for sym, entry in manifest["symbols"].items():
    rows = {r[0]: r for r in frozen.get(sym, [])}
    path = FORWARD / entry["file"]
    if path.exists():
        rows.update({r[0]: r for r in ls._read_symbol(path)})
    extended[sym] = sorted(rows.values())

base = params_from_preset(RunStrategySkill.PRESETS["limit scanner"])
TAKER_BP = 6.0
rows = []
for name, params, spec, at_close in [
    ("V0_fixed_realistic", *ls.variant_params(base, "V0"), False),
    ("V1_reclaim (as pre-registered)", *ls.variant_params(base, "V1"), False),
    ("V1_reclaim, enter at close, taker", ls.variant_params(base, "V1")[0],
     replace(ls.variant_params(base, "V1")[1], name="reclaim_close_taker", entry_fee_bp=TAKER_BP), True),
    ("V1_reclaim, enter at close, maker", ls.variant_params(base, "V1")[0],
     replace(ls.variant_params(base, "V1")[1], name="reclaim_close_maker"), True),
    ("V2_vol_offset", *ls.variant_params(base, "V2"), False),
    ("V3_reclaim_neutral (as pre-registered)", *ls.variant_params(base, "V3"), False),
    ("V3_reclaim_neutral, enter at close, taker", ls.variant_params(base, "V3")[0],
     replace(ls.variant_params(base, "V3")[1], name="reclaim_neutral_close_taker", entry_fee_bp=TAKER_BP), True),
]:
    ENTER_AT_CLOSE = at_close
    fz = ls.simulate(frozen, params, spec)["trades"]
    ex = ls.simulate(extended, params, spec)["trades"]
    forward = [t for t in ex if int(t["fill_ms"]) > ls.FORWARD_CUTOFF_MS]
    rows.append({
        "name": name,
        "dev": ls.summarize(ls.slice_trades(fz, 0, ls.HOLDOUT_START_MS)),
        "holdout": ls.summarize(ls.slice_trades(fz, ls.HOLDOUT_START_MS, ls.FORWARD_CUTOFF_MS + 1)),
        "forward": ls.summarize(forward),
        "forward_verdict": ls.evaluate_forward(forward, funding_priced=False),
        "forward_last_fill_ms": max((int(t["fill_ms"]) for t in forward), default=None),
    })
    print(name, "done", file=sys.stderr, flush=True)

print(json.dumps({"label": "POST-HOC diagnostic; cannot pass the pre-registered bar",
                  "dataset_failed": failed,
                  "extended_last_bar_ms": max(r[-1][0] for r in extended.values() if r),
                  "taker_bp": TAKER_BP, "maker_bp": ls.MAKER_BP, "rows": rows}, indent=1, default=str))
